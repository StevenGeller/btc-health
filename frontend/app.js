// Bitcoin Health Scorecard Frontend Application

const API_BASE = window.location.protocol + '//' + window.location.hostname + '/api';
let currentPeriod = 30;
let historyChart = null;
let sparklineChart = null;

// Pillar configurations
const PILLAR_CONFIG = {
    security: {
        name: 'Security & Mining Economics',
        icon: '🛡️',
        weight: 30,
        color: '#ff6b6b'
    },
    decent: {
        name: 'Decentralization & Resilience',
        icon: '🌐',
        weight: 25,
        color: '#4ecdc4'
    },
    throughput: {
        name: 'Throughput & Mempool',
        icon: '⚡',
        weight: 15,
        color: '#45b7d1'
    },
    adoption: {
        name: 'Adoption & Protocol',
        icon: '📈',
        weight: 15,
        color: '#96ceb4'
    },
    lightning: {
        name: 'Lightning Network',
        icon: '⚡',
        weight: 15,
        color: '#ffeaa7'
    }
};

// Initialize the application
document.addEventListener('DOMContentLoaded', () => {
    initializeApp();
    loadLatestScores();
    loadHistoricalData(currentPeriod);
    loadCollectorStatus();
    
    // Set up auto-refresh
    setInterval(loadLatestScores, 60000); // Refresh every minute
    
    // Set up period buttons
    document.querySelectorAll('.period-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            document.querySelectorAll('.period-btn').forEach(b => b.classList.remove('active'));
            e.target.classList.add('active');
            currentPeriod = parseInt(e.target.dataset.period);
            loadHistoricalData(currentPeriod);
        });
    });
});

function initializeApp() {
    // Initialize charts
    const ctx = document.getElementById('history-chart').getContext('2d');
    historyChart = new Chart(ctx, {
        type: 'line',
        data: {
            datasets: []
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false,
            },
            plugins: {
                legend: {
                    display: true,
                    position: 'top',
                },
                tooltip: {
                    mode: 'index',
                    intersect: false,
                }
            },
            scales: {
                x: {
                    type: 'time',
                    time: {
                        tooltipFormat: 'MMM dd, yyyy HH:mm',
                        displayFormats: {
                            hour: 'MMM dd HH:mm',
                            day: 'MMM dd',
                            week: 'MMM dd',
                            month: 'MMM yyyy'
                        }
                    },
                    title: {
                        display: true,
                        text: 'Date'
                    }
                },
                y: {
                    title: {
                        display: true,
                        text: 'Score (0-100)'
                    },
                    min: 0,
                    max: 100
                }
            }
        }
    });
    
    // Initialize sparkline
    const sparkCtx = document.getElementById('overall-sparkline').getContext('2d');
    sparklineChart = new Chart(sparkCtx, {
        type: 'line',
        data: {
            datasets: [{
                data: [],
                borderColor: '#f7931a',
                backgroundColor: 'rgba(247, 147, 26, 0.1)',
                borderWidth: 2,
                pointRadius: 0,
                tension: 0.4,
                fill: true
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: { enabled: false }
            },
            scales: {
                x: { display: false },
                y: { display: false, min: 0, max: 100 }
            }
        }
    });
}

async function loadLatestScores() {
    try {
        const response = await fetch(`${API_BASE}/score/latest`);
        const data = await response.json();
        
        // Update overall score
        updateOverallScore(data.overall, data.trend_7d, data.trend_30d);
        
        // Update pillars
        updatePillars(data.pillars);
        
        // Update last update time
        const updateTime = new Date(data.last_updated * 1000);
        document.getElementById('last-update').textContent = updateTime.toLocaleString();
        
        // Load additional data
        loadPriceData();
        loadBlockHeight();
        
    } catch (error) {
        console.error('Error loading scores:', error);
        showError('Failed to load latest scores');
    }
}

function updateOverallScore(score, trend7d, trend30d) {
    // Update score display
    const scoreElement = document.getElementById('overall-score');
    scoreElement.textContent = Math.round(score);
    
    // Update gauge
    const arc = document.getElementById('score-arc');
    const angle = (score / 100) * 160; // 160 degrees for the arc
    const endX = 100 + 80 * Math.cos((angle - 80) * Math.PI / 180);
    const endY = 100 + 80 * Math.sin((angle - 80) * Math.PI / 180);
    const largeArc = angle > 90 ? 1 : 0;
    arc.setAttribute('d', `M 20 100 A 80 80 0 ${largeArc} 1 ${endX} ${endY}`);
    
    // Update trends
    updateTrend('trend-7d', trend7d);
    updateTrend('trend-30d', trend30d);
    
    // Color code the score
    let color;
    if (score >= 75) color = '#00d4aa';
    else if (score >= 50) color = '#ffaa00';
    else color = '#ff4444';
    scoreElement.style.color = color;
}

function updateTrend(elementId, value) {
    const element = document.getElementById(elementId);
    if (value !== null && value !== undefined) {
        const sign = value > 0 ? '+' : '';
        element.textContent = `${sign}${value.toFixed(1)}%`;
        element.className = 'trend-value ' + (value > 0 ? 'positive' : value < 0 ? 'negative' : '');
    } else {
        element.textContent = 'N/A';
        element.className = 'trend-value';
    }
}

function updatePillars(pillars) {
    const grid = document.getElementById('pillars-grid');
    grid.innerHTML = '';
    
    Object.entries(pillars).forEach(([pillarId, pillar]) => {
        const config = PILLAR_CONFIG[pillarId];
        const card = createPillarCard(pillarId, pillar, config);
        grid.appendChild(card);
    });
}

function createPillarCard(pillarId, pillar, config) {
    const card = document.createElement('div');
    card.className = 'pillar-card';
    card.dataset.pillar = pillarId;
    
    const metricsHtml = Object.entries(pillar.metrics || {}).slice(0, 3).map(([metricId, metric]) => {
        const value = formatMetricValue(metricId, metric);
        return `
            <div class="metric-item">
                <span class="metric-name">${getMetricName(metricId)}</span>
                <span class="metric-value">${value}</span>
            </div>
        `;
    }).join('');
    
    card.innerHTML = `
        <div class="pillar-header">
            <div class="pillar-icon">${config.icon}</div>
            <div class="pillar-info">
                <h3>${pillar.name}</h3>
                <span class="pillar-weight">${config.weight}% weight</span>
            </div>
        </div>
        <div class="pillar-score">
            <div class="score-bar">
                <div class="score-fill" style="width: ${pillar.score}%; background: ${getScoreColor(pillar.score)}"></div>
            </div>
            <span class="score-text">${Math.round(pillar.score)}</span>
        </div>
        <div class="pillar-metrics">
            ${metricsHtml}
        </div>
        <button class="details-btn" onclick="showPillarDetails('${pillarId}')">View Details</button>
    `;
    
    return card;
}

function getMetricName(metricId) {
    const names = {
        'security.difficulty_momentum': 'Difficulty Momentum',
        'security.fee_share': 'Fee Share',
        'security.hashprice': 'Hashprice',
        'security.stale_incidence': 'Stale Blocks',
        'decent.pool_hhi': 'Pool Concentration',
        'decent.node_asn_hhi': 'Node ASN Diversity',
        'decent.client_entropy': 'Client Diversity',
        'throughput.mempool_pressure': 'Mempool Pressure',
        'throughput.fee_elasticity': 'Fee Elasticity',
        'throughput.confirm_latency': 'Confirmation Time',
        'adoption.utxo_growth': 'UTXO Growth',
        'adoption.segwit_usage': 'SegWit Usage',
        'adoption.rbf_activity': 'RBF Activity',
        'lightning.capacity_growth': 'Capacity Growth',
        'lightning.node_concentration': 'Node Concentration'
    };
    return names[metricId] || metricId.split('.').pop();
}

function formatMetricValue(metricId, metric) {
    if (!metric.value && metric.value !== 0) {
        return `${Math.round(metric.score)}/100`;
    }
    
    const value = metric.value;
    const unit = metric.unit;
    
    // Format based on metric type
    if (metricId.includes('hhi') || metricId.includes('entropy')) {
        return value.toFixed(4);
    } else if (metricId.includes('share') || metricId.includes('usage')) {
        return `${(value * 100).toFixed(1)}%`;
    } else if (metricId.includes('growth')) {
        return `${value > 0 ? '+' : ''}${(value * 100).toFixed(1)}%`;
    } else if (unit === 'USD/TH/day') {
        return `$${value.toFixed(2)}`;
    } else if (unit === 'incidents/day') {
        return value.toFixed(3);
    } else {
        return value.toFixed(2) + (unit ? ` ${unit}` : '');
    }
}

function getScoreColor(score) {
    if (score >= 75) return 'linear-gradient(90deg, #00d4aa, #00ff00)';
    if (score >= 50) return 'linear-gradient(90deg, #ffaa00, #ffd700)';
    return 'linear-gradient(90deg, #ff4444, #ff6666)';
}

async function loadHistoricalData(days) {
    try {
        // Load overall score history
        const overallResponse = await fetch(`${API_BASE}/score/timeseries?kind=overall&id=overall&days=${days}`);
        const overallData = await overallResponse.json();
        
        // Load pillar histories
        const pillarPromises = Object.keys(PILLAR_CONFIG).map(async (pillarId) => {
            const response = await fetch(`${API_BASE}/score/timeseries?kind=pillar&id=${pillarId}&days=${days}`);
            return response.json();
        });
        
        const pillarData = await Promise.all(pillarPromises);
        
        // Update chart
        updateHistoryChart(overallData, pillarData);
        
        // Update sparkline
        updateSparkline(overallData.data);
        
    } catch (error) {
        console.error('Error loading historical data:', error);
    }
}

function updateHistoryChart(overallData, pillarData) {
    const datasets = [
        {
            label: 'Overall Score',
            data: overallData.data.map(d => ({
                x: d.timestamp * 1000,
                y: d.value
            })),
            borderColor: '#f7931a',
            backgroundColor: 'rgba(247, 147, 26, 0.1)',
            borderWidth: 3,
            tension: 0.4
        }
    ];
    
    pillarData.forEach((pillar, index) => {
        const pillarId = Object.keys(PILLAR_CONFIG)[index];
        const config = PILLAR_CONFIG[pillarId];
        datasets.push({
            label: config.name,
            data: pillar.data.map(d => ({
                x: d.timestamp * 1000,
                y: d.value
            })),
            borderColor: config.color,
            backgroundColor: config.color + '20',
            borderWidth: 2,
            tension: 0.4,
            hidden: true // Start with pillars hidden
        });
    });
    
    historyChart.data.datasets = datasets;
    historyChart.update();
}

function updateSparkline(data) {
    // Take last 30 data points for sparkline
    const recentData = data.slice(-30).map(d => ({
        x: d.timestamp * 1000,
        y: d.value
    }));
    
    sparklineChart.data.datasets[0].data = recentData;
    sparklineChart.update();
}

async function loadPriceData() {
    try {
        const response = await fetch(`${API_BASE}/metrics/price.btc_usd`);
        const data = await response.json();
        
        if (data.latest_value) {
            document.getElementById('btc-price').textContent = `$${data.latest_value.toLocaleString()}`;
        }
    } catch (error) {
        console.error('Error loading price:', error);
    }
}

async function loadBlockHeight() {
    try {
        // This would need a specific endpoint or external API
        // For now, using a placeholder
        const response = await fetch('https://mempool.space/api/blocks/tip/height');
        const height = await response.text();
        document.getElementById('block-height').textContent = parseInt(height).toLocaleString();
    } catch (error) {
        console.error('Error loading block height:', error);
        document.getElementById('block-height').textContent = 'N/A';
    }
}

async function loadCollectorStatus() {
    try {
        const response = await fetch(`${API_BASE}/collectors/status`);
        const data = await response.json();
        
        const grid = document.getElementById('sources-grid');
        grid.innerHTML = '';
        
        const collectorMap = {
            'mempool': 'mempool.space',
            'bitnodes': 'Bitnodes',
            'blockchain_charts': 'Blockchain.com',
            'coingecko': 'CoinGecko',
            'forkmonitor': 'ForkMonitor'
        };
        
        Object.entries(collectorMap).forEach(([key, name]) => {
            const collector = data.collectors.find(c => c.name === key);
            const item = document.createElement('div');
            item.className = 'source-item';
            
            let statusClass = 'healthy';
            let statusSymbol = '●';
            
            if (collector) {
                if (collector.consecutive_failures > 3) {
                    statusClass = 'error';
                } else if (collector.consecutive_failures > 0) {
                    statusClass = 'warning';
                }
            } else {
                statusClass = 'error';
                statusSymbol = '○';
            }
            
            item.innerHTML = `
                <span class="source-name">${name}</span>
                <span class="source-status ${statusClass}">${statusSymbol}</span>
            `;
            
            grid.appendChild(item);
        });
        
    } catch (error) {
        console.error('Error loading collector status:', error);
    }
}

async function showPillarDetails(pillarId) {
    const modal = document.getElementById('detail-modal');
    const modalTitle = document.getElementById('modal-title');
    const modalBody = document.getElementById('modal-body');
    
    try {
        // Load detailed metrics for the pillar
        const response = await fetch(`${API_BASE}/score/latest`);
        const data = await response.json();
        
        const pillar = data.pillars[pillarId];
        const config = PILLAR_CONFIG[pillarId];
        
        modalTitle.textContent = `${config.name} Details`;
        
        let metricsHtml = '<h3>Metrics Breakdown</h3><div class="metrics-detail">';
        
        for (const [metricId, metric] of Object.entries(pillar.metrics)) {
            const metricResponse = await fetch(`${API_BASE}/metrics/${metricId}`);
            const metricDetail = await metricResponse.json();
            
            metricsHtml += `
                <div class="metric-detail-card">
                    <h4>${metricDetail.name}</h4>
                    <p class="metric-description">${metricDetail.description}</p>
                    <div class="metric-stats">
                        <div class="stat-item">
                            <span class="stat-label">Score</span>
                            <span class="stat-value">${Math.round(metric.score)}/100</span>
                        </div>
                        <div class="stat-item">
                            <span class="stat-label">Value</span>
                            <span class="stat-value">${formatMetricValue(metricId, metric)}</span>
                        </div>
                        <div class="stat-item">
                            <span class="stat-label">7d Trend</span>
                            <span class="stat-value ${metric.trend_7d > 0 ? 'positive' : metric.trend_7d < 0 ? 'negative' : ''}">
                                ${metric.trend_7d ? (metric.trend_7d > 0 ? '+' : '') + metric.trend_7d.toFixed(1) + '%' : 'N/A'}
                            </span>
                        </div>
                    </div>
                    ${metricDetail.percentiles ? `
                        <div class="percentiles">
                            <span>Percentiles: </span>
                            <span>P10: ${metricDetail.percentiles.p10.toFixed(2)}</span>
                            <span>P50: ${metricDetail.percentiles.p50.toFixed(2)}</span>
                            <span>P90: ${metricDetail.percentiles.p90.toFixed(2)}</span>
                        </div>
                    ` : ''}
                </div>
            `;
        }
        
        metricsHtml += '</div>';
        
        modalBody.innerHTML = metricsHtml + `
            <style>
                .metrics-detail {
                    display: grid;
                    gap: 20px;
                    margin-top: 20px;
                }
                .metric-detail-card {
                    background: #f5f5f5;
                    padding: 15px;
                    border-radius: 8px;
                }
                .metric-detail-card h4 {
                    margin: 0 0 10px 0;
                    color: #2c3e50;
                }
                .metric-description {
                    color: #7f8c8d;
                    font-size: 14px;
                    margin: 10px 0;
                }
                .metric-stats {
                    display: flex;
                    gap: 20px;
                    margin: 15px 0;
                }
                .stat-item {
                    flex: 1;
                }
                .stat-label {
                    display: block;
                    font-size: 12px;
                    color: #7f8c8d;
                    text-transform: uppercase;
                }
                .stat-value {
                    display: block;
                    font-size: 18px;
                    font-weight: 600;
                    margin-top: 5px;
                }
                .percentiles {
                    font-size: 12px;
                    color: #7f8c8d;
                    margin-top: 10px;
                }
                .percentiles span {
                    margin-right: 15px;
                }
            </style>
        `;
        
        modal.style.display = 'block';
        
    } catch (error) {
        console.error('Error loading pillar details:', error);
        modalBody.innerHTML = '<p>Error loading details. Please try again.</p>';
        modal.style.display = 'block';
    }
}

function closeModal() {
    document.getElementById('detail-modal').style.display = 'none';
}

// Close modal when clicking outside
window.onclick = function(event) {
    const modal = document.getElementById('detail-modal');
    if (event.target === modal) {
        modal.style.display = 'none';
    }
}

function showError(message) {
    console.error(message);
    // Could add a toast notification here
}
