# Bitcoin Health Scorecard - Metrics Guide

## Overall Health Score (0-100)
Weighted average of 5 pillars. Higher = healthier network.

## 🛡️ Security & Mining Economics (30% weight)
**Why it matters:** Network security against 51% attacks and long-term sustainability.

### Key Metrics:
- **Hashrate**: Total network computing power (EH/s). Higher = more expensive to attack
- **Difficulty**: Auto-adjusts every 2016 blocks. Tracks security level
- **Hashprice**: Mining profitability ($/TH/day). Sweet spot: $50-100
- **Fee Share**: Fees as % of miner revenue. Target >10% by 2028 for post-subsidy security

### Score Interpretation:
- 80-100: Extremely secure, well-incentivized miners
- 60-80: Healthy security, sustainable economics  
- 40-60: Adequate but watch for miner capitulation
- 20-40: Security concerns, miners struggling
- 0-20: Critical - vulnerable to attacks

## 🌐 Decentralization & Resilience (25% weight)
**Why it matters:** Censorship resistance and no single points of failure.

### Key Metrics:
- **Mining Pool HHI**: Concentration index. <0.15 good, >0.25 dangerous
- **Node Distribution**: Geographic/ISP diversity. Lower HHI = better
- **Client Diversity**: Multiple implementations reduce bug risk

### Score Interpretation:
- 80-100: Highly decentralized, very resilient
- 60-80: Good distribution, low centralization risk
- 40-60: Some concentration concerns
- 20-40: Significant centralization risks
- 0-20: Dangerous concentration of power

## 📈 Throughput & Efficiency (15% weight)
**Why it matters:** User experience and network scalability.

### Key Metrics:
- **Mempool Size**: Backlog in MB. <5MB smooth, >50MB congested
- **Tx per Block**: Efficiency of block space usage
- **Fee Market**: How well fees respond to demand
- **Confirmation Time**: Average wait for inclusion

### Score Interpretation:
- 80-100: Smooth operations, efficient fee market
- 60-80: Good throughput, occasional congestion
- 40-60: Regular congestion, fee spikes
- 20-40: Poor UX, high fees, long waits
- 0-20: Severely congested, unusable for many

## 💹 Adoption & Growth (15% weight)
**Why it matters:** Network effects and long-term value.

### Key Metrics:
- **UTXO Count**: Total unspent outputs. Growing = more holders
- **Active Addresses**: Daily economic activity
- **SegWit Adoption**: Technical progress indicator. Target >90%
- **UTXO Growth Rate**: Expansion of holder base

### Score Interpretation:
- 80-100: Rapid growth, strong adoption
- 60-80: Steady growth, healthy adoption
- 40-60: Slow growth, adoption lagging
- 20-40: Stagnant or declining usage
- 0-20: Significant user exodus

## ⚡ Lightning Network (15% weight)
**Why it matters:** Layer 2 scaling for instant micropayments.

### Key Metrics:
- **Capacity**: Total BTC in channels. Growing = maturing
- **Channels**: Payment routes available
- **Nodes**: Network participants
- **Growth Rate**: Monthly capacity change. Target >5%
- **Concentration**: Top nodes share. Lower = better

### Score Interpretation:
- 80-100: Thriving L2 ecosystem
- 60-80: Healthy growth, good adoption
- 40-60: Slow but steady progress
- 20-40: Stagnant or centralizing
- 0-20: Failing to gain traction

## Critical Thresholds

### 🚨 Red Flags (Immediate Concern):
- Mining Pool HHI >0.25 (51% attack risk)
- Top 3 pools >50% (collusion risk)
- Hashprice <$40 (miner capitulation)
- Mempool >300MB (severe congestion)
- UTXO growth negative for 30+ days

### ⚠️ Warning Signs (Monitor Closely):
- Fee share <5% (security unsustainability)
- SegWit adoption <60% (technical lag)
- Lightning capacity declining 3+ months
- Active addresses down 50% from peak
- Client diversity <0.5 (implementation risk)

### ✅ Health Indicators:
- Hashrate at all-time highs
- Pool HHI <0.15
- Fee market responsive (elasticity >1)
- UTXO count growing steadily
- Lightning capacity doubling yearly

## Understanding Your Score

### 70-100: Excellent Health
Bitcoin is thriving across all dimensions. Strong security, good decentralization, efficient operations.

### 50-70: Good Health
Generally healthy but some areas need attention. Monitor weak pillars.

### 30-50: Fair Health
Multiple concerns. Network functional but facing challenges. Action needed.

### 20-30: Poor Health
Significant problems across multiple pillars. Network stressed.

### 0-20: Critical
Severe issues threatening network viability. Immediate attention required.

## Data Sources
- **Your Umbrel Node**: Real-time blockchain and Lightning data
- **Mempool.space**: Mempool and mining pool statistics
- **Binance**: Price and market data
- **Blockchain.com**: Historical metrics
- **Your LND Node**: Lightning Network insights

Updated every 15 minutes for real-time health monitoring.