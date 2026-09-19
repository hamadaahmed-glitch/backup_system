#!/usr/bin/env bash
#
# test_network_limits.sh
# Run this on the LAPTOP to benchmark network and SSH throughput to Desktop.
#

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $1" >&2; }

echo "================================================================="
echo "            NETWORK & SSH PERFORMANCE BENCHMARK                  "
echo "================================================================="

read -rp "Enter Desktop IP address: " DESKTOP_IP
read -rp "Enter Desktop username [default: backup-user]: " DESKTOP_USER
DESKTOP_USER=${DESKTOP_USER:-backup-user}

read -rp "Enter Desktop SSH Port [default: 22]: " DESKTOP_PORT
DESKTOP_PORT=${DESKTOP_PORT:-22}

read -rp "Path to SSH private key [default: ~/.ssh/id_ed25519_backup]: " KEY_PATH
KEY_PATH=${KEY_PATH:-~/.ssh/id_ed25519_backup}
KEY_PATH=$(eval echo "$KEY_PATH")

SSH_CMD="ssh -i $KEY_PATH -p $DESKTOP_PORT -o BatchMode=yes -o StrictHostKeyChecking=accept-new ${DESKTOP_USER}@${DESKTOP_IP}"

# 1. Ping Latency Check
log_info "Step 1: Measuring round-trip ICMP network latency..."
if ping -c 4 "$DESKTOP_IP" > /tmp/ping_res.txt 2>&1; then
    AVG_PING=$(tail -n 1 /tmp/ping_res.txt | awk -F '/' '{print $5}')
    echo -e " Average Latency: ${CYAN}${AVG_PING} ms${NC}"
else
    log_warn "Ping blocked or timed out. Proceeding to TCP tests."
fi

# 2. SSH Stream Throughput Test (Tests CPU encryption + network wire speed)
TEST_SIZE_MB=1024  # 1 GB
log_info "Step 2: Streaming ${TEST_SIZE_MB}MB uncompressed stream over SSH to /dev/null..."
echo "Testing effective transfer rate..."

START_TIME=$(date +%s.%N)
dd if=/dev/zero bs=1M count="$TEST_SIZE_MB" 2>/dev/null | $SSH_CMD "cat > /dev/null"
END_TIME=$(date +%s.%N)

DURATION=$(echo "$END_TIME - $START_TIME" | bc)
MBPS=$(echo "scale=2; $TEST_SIZE_MB / $DURATION" | bc)
GBIT=$(echo "scale=2; ($MBPS * 8) / 1024" | bc)

echo ""
echo "================================================================="
log_success "SSH Throughput Benchmark Completed!"
echo "================================================================="
echo -e " Data Transferred : ${CYAN}${TEST_SIZE_MB} MB${NC}"
echo -e " Elapsed Time     : ${CYAN}${DURATION} seconds${NC}"
echo -e " Real Throughput  : ${GREEN}${MBPS} MB/s${NC} (~${GREEN}${GBIT} Gbps${NC})"
echo "================================================================="

# Interpretation advice
if (( $(echo "$MBPS > 90.0" | bc -l) )); then
    echo -e "Network assessment: ${GREEN}Optimal (Full Gigabit Ethernet detected).${NC}"
    echo "170 GB will take approximately 25-30 minutes."
elif (( $(echo "$MBPS > 35.0" | bc -l) )); then
    echo -e "Network assessment: ${YELLOW}Moderate (Fast Wi-Fi or throttled connection).${NC}"
    echo "170 GB will take approximately 1.5 - 2 hours."
else
    echo -e "Network assessment: ${RED}Suboptimal (Slow Wi-Fi or network bottleneck).${NC}"
    echo "Using a wired Gigabit Ethernet cable is highly recommended for 170 GB."
fi

# 3. Optional iPerf3 Benchmark
if command -v iperf3 &>/dev/null; then
    echo ""
    log_info "Step 3: Checking for iperf3 service on Desktop..."
    if $SSH_CMD "command -v iperf3" &>/dev/null; then
        log_info "Running iperf3 raw TCP bandwidth test..."
        # Start remote daemon temporarily
        $SSH_CMD "iperf3 -s -D" >/dev/null 2>&1 || true
        sleep 1
        iperf3 -c "$DESKTOP_IP" -t 5 || true
    else
        log_info "iperf3 is not installed on the Desktop. Skipping raw TCP test."
    fi
fi

echo ""