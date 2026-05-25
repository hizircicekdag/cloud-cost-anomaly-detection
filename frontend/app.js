// Global durum değişkenleri
let costData = [];
let alertsData = [];
let summaryData = {};
let metricsData = {};

// Chart.js grafik referansları
let charts = {
    timeline: null,
    serviceSplit: null,
    metrics: null,
    stlTrend: null,
    stlSeasonal: null,
    stlResidual: null,
    prCurve: null
};

// Varsayılan model algılama parametreleri
let params = {
    stl_threshold: 3.0,
    iforest_contamination: 0.05,
    zscore_threshold: 2.5
};

const BASE_API_URL = "http://127.0.0.1:8000/api";

// Sekmelere göre başlık ve alt başlık eşleşmeleri
const tabMeta = {
    "dashboard-tab": { title: "Anomali Panosu", subtitle: "Gerçek Zamanlı AWS Faturalandırma Analitiği" },
    "analysis-tab": { title: "Model Metrikleri & Analiz", subtitle: "Zaman serisi ayrıştırması ve algoritmaların doğruluğu" },
    "alerts-tab": { title: "Tarihsel Alarmlar ve Kök Neden Analizi", subtitle: "Anomali ve kök neden kayıt defteri" },
    "simulator-tab": { title: "Arıza Simülatörü", subtitle: "Sistemin eşik değerlerini ve modelleri test edin" }
};

document.addEventListener("DOMContentLoaded", () => {
    // 1. İlk Yükleme
    refreshAllData();
    setupNavigation();
    setupEventListeners();
});

// Menü geçişleri
function setupNavigation() {
    const navItems = document.querySelectorAll(".nav-item");
    const tabContents = document.querySelectorAll(".tab-content");
    const pageTitle = document.getElementById("page-title");
    const pageSubtitle = document.getElementById("page-subtitle");

    navItems.forEach(item => {
        item.addEventListener("click", () => {
            const targetTab = item.getAttribute("data-tab");

            // Tümünü devre dışı bırak
            navItems.forEach(nav => nav.classList.remove("active"));
            tabContents.forEach(tab => tab.classList.remove("active"));

            // Seçileni aktifleştir
            item.classList.add("active");
            document.getElementById(targetTab).classList.add("active");

            // Başlıkları güncelle
            if (tabMeta[targetTab]) {
                pageTitle.textContent = tabMeta[targetTab].title;
                pageSubtitle.textContent = tabMeta[targetTab].subtitle;
            }

            // Grafik boyutlarını yenile (Chart.js piksel hatalarını önler)
            setTimeout(() => {
                triggerChartResize();
            }, 100);
        });
    });
}

function setupEventListeners() {
    // Parametreleri güncelleme
    document.getElementById("btn-update-params").addEventListener("click", () => {
        params.stl_threshold = parseFloat(document.getElementById("param-stl").value) || 3.0;
        params.iforest_contamination = parseFloat(document.getElementById("param-if").value) || 0.05;
        params.zscore_threshold = parseFloat(document.getElementById("param-z").value) || 2.5;

        showModal("Parametreler Güncellendi", "Yeni model eşik değerleri kullanılarak maliyetler analiz ediliyor...", () => {
            refreshAllData();
        });
    });

    // Simülatörden anomali enjekte etme
    const simForm = document.getElementById("simulator-form");
    simForm.addEventListener("submit", (e) => {
        e.preventDefault();
        const payload = {
            date: document.getElementById("sim-date").value,
            service: document.getElementById("sim-service").value,
            spike_amount: parseFloat(document.getElementById("sim-spike").value),
            reason: document.getElementById("sim-reason").value
        };

        injectAnomaly(payload);
    });

    // Şablon butonları ile anomali ekleme
    const presetBtns = document.querySelectorAll(".preset-btn");
    presetBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            // Veri seti aralığında rastgele bir gün seç (Kasım 2025 - Nisan 2026 arası)
            const randomDaysOffset = Math.floor(Math.random() * 120) + 35;
            const baseDate = new Date("2025-11-27");
            baseDate.setDate(baseDate.getDate() + randomDaysOffset);
            const dateStr = baseDate.toISOString().split('T')[0];

            const payload = {
                date: dateStr,
                service: btn.getAttribute("data-service"),
                spike_amount: parseFloat(btn.getAttribute("data-spike")),
                reason: btn.getAttribute("data-reason")
            };
            
            injectAnomaly(payload);
        });
    });

    // Veritabanını sıfırlama
    document.getElementById("btn-reset-db").addEventListener("click", () => {
        fetch(`${BASE_API_URL}/reset`, { method: "POST" })
            .then(res => res.json())
            .then(data => {
                showModal("Veri Tabanı Sıfırlandı", "Sentetik bulut fatura verileri varsayılan ayarlara döndürüldü.", () => {
                    refreshAllData();
                });
            })
            .catch(err => console.error("Database sıfırlama hatası:", err));
    });

    // Modalı kapatma butonu
    document.getElementById("btn-close-modal").addEventListener("click", hideModal);

    // Grafik filtre seçenekleri
    const toggles = ["toggle-gt", "toggle-stl", "toggle-iforest", "toggle-zscore"];
    toggles.forEach(id => {
        document.getElementById(id).addEventListener("change", () => {
            renderCostTimelineChart();
        });
    });

    // Tablo filtre seçeneği
    document.getElementById("filter-model").addEventListener("change", (e) => {
        loadAlerts(e.target.value);
    });
}

// Verileri güncelleme
function refreshAllData() {
    // 1. Özet İstatistikler
    fetch(`${BASE_API_URL}/summary`)
        .then(res => res.json())
        .then(data => {
            summaryData = data;
            updateKPICards();
        })
        .catch(err => console.error("Özet yükleme hatası:", err));

    // 2. Maliyet Verileri
    const queryParams = `?stl_threshold=${params.stl_threshold}&iforest_contamination=${params.iforest_contamination}&zscore_threshold=${params.zscore_threshold}`;
    
    fetch(`${BASE_API_URL}/cost-data${queryParams}`)
        .then(res => res.json())
        .then(data => {
            costData = data;
            renderCostTimelineChart();
            renderServiceSplitChart();
            renderSTLDecompositionCharts();
        })
        .catch(err => console.error("Maliyet verisi yükleme hatası:", err));

    // 3. Model Doğruluk Metrikleri (Analiz Tabı)
    fetch(`${BASE_API_URL}/metrics${queryParams}`)
        .then(res => res.json())
        .then(data => {
            metricsData = data;
            renderMetricsChart();
            renderMetricsTable();
            updateF1ScoreMaxKPI();
        })
        .catch(err => console.error("Metrik yükleme hatası:", err));

    // 3.5. Precision-Recall Eğrisi Verilerini Yükle (Rapor Bölüm 5)
    fetch(`${BASE_API_URL}/pr-curve`)
        .then(res => res.json())
        .then(data => {
            renderPRCurveChart(data);
        })
        .catch(err => console.error("PR Eğrisi yükleme hatası:", err));

    // 4. Alarmlar Listesi
    loadAlerts();
}

function loadAlerts(filterModel = "any") {
    const queryParams = `?model=${filterModel}&stl_threshold=${params.stl_threshold}&iforest_contamination=${params.iforest_contamination}&zscore_threshold=${params.zscore_threshold}`;
    fetch(`${BASE_API_URL}/alerts${queryParams}`)
        .then(res => res.json())
        .then(data => {
            alertsData = data;
            
            if (filterModel === "any") {
                const activeCount = data.filter(a => a.detected_by.length > 0).length;
                document.getElementById("alert-badge-count").textContent = activeCount;
                document.getElementById("kpi-anomalies").textContent = activeCount;
                
                const gtCount = data.filter(a => a.is_anomaly_gt === 1).length;
                document.getElementById("kpi-anomalies-footer").textContent = `Enjekte edilen referans: ${gtCount}`;
                
                const alertCard = document.querySelector(".alert-card");
                if (activeCount > 0) {
                    alertCard.classList.add("critical");
                } else {
                    alertCard.classList.remove("critical");
                }

                // Dashboard Alarmlar Önizlemesi (Son 5 adet)
                renderRecentAlertsFeed(data.slice(0, 5));
            }

            // Detaylı Log Tablosu
            renderAlertsTable(data);
        })
        .catch(err => console.error("Alarmlar yükleme hatası:", err));
}

// Anomali enjeksiyonu
function injectAnomaly(payload) {
    fetch(`${BASE_API_URL}/inject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
    })
    .then(res => {
        if (!res.ok) return res.json().then(d => { throw new Error(d.detail) });
        return res.json();
    })
    .then(data => {
        showModal("Anomali Enjekte Edildi", `Başarıyla ${payload.date} tarihine ${payload.service} servisi için $${payload.spike_amount} maliyet sıçraması eklendi. Modeller yeniden hesaplanıyor.`, () => {
            refreshAllData();
        });
    })
    .catch(err => {
        showModal("Enjeksiyon Başarısız", `Hata: ${err.message}`);
    });
}

// KPI güncelleme
function updateKPICards() {
    if (summaryData.total_cost) {
        document.getElementById("kpi-total-cost").textContent = formatCurrency(summaryData.total_cost);
        document.getElementById("kpi-avg-cost").textContent = formatCurrency(summaryData.avg_daily_cost);
    }
}

function updateF1ScoreMaxKPI() {
    if (metricsData.STL) {
        const maxF1 = Math.max(
            metricsData.STL.f1_score,
            metricsData.IsolationForest.f1_score,
            metricsData.ZScore.f1_score
        );
        document.getElementById("kpi-efficiency").textContent = `${(maxF1 * 100).toFixed(1)}%`;
    }
}

// Dashboard mini uyarı akışı
function renderRecentAlertsFeed(alerts) {
    const feed = document.getElementById("recent-alerts-feed");
    feed.innerHTML = "";

    if (alerts.length === 0) {
        feed.innerHTML = `<div class="feed-empty">Maliyet zaman çizelgesinde anomali bulunmuyor.</div>`;
        return;
    }

    alerts.forEach(alert => {
        const div = document.createElement("div");
        div.className = "feed-item critical animate-fade-in";
        
        let modelsString = alert.detected_by.join(", ");
        if (!modelsString) modelsString = "Modeller yakalayamadı (Referans veri)";
        
        const badgeClass = alert.confidence === "Yüksek" ? "badge-high" : (alert.confidence === "Orta" ? "badge-medium" : "badge-low");

        div.innerHTML = `
            <div class="feed-left">
                <span class="feed-date">${alert.date}</span>
                <span class="feed-title">${alert.primary_service} Sıçraması</span>
                <span class="feed-desc">${alert.root_cause_explanation}</span>
            </div>
            <div class="feed-right">
                <span class="feed-cost">+${formatCurrency(alert.breakdown[0]?.spike_amount || 0)}</span>
                <span class="feed-badge ${badgeClass}">${alert.confidence} Güven</span>
            </div>
        `;
        feed.appendChild(div);
    });
}

// Detaylı alarmlar listesi tablosu
function renderAlertsTable(alerts) {
    const tbody = document.getElementById("alerts-log-table-body");
    tbody.innerHTML = "";

    if (alerts.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted);">Seçilen filtreye uygun alarm kaydı bulunamadı.</td></tr>`;
        return;
    }

    alerts.forEach(alert => {
        const tr = document.createElement("tr");
        
        // Etiketler
        let tagsHtml = "";
        alert.detected_by.forEach(m => {
            let cls = m === "STL" ? "tag-stl" : (m === "Isolation Forest" ? "tag-iforest" : "tag-zscore");
            tagsHtml += `<span class="tag ${cls}">${m === "Isolation Forest" ? "I-Forest" : m}</span> `;
        });
        if (alert.is_anomaly_gt === 1) {
            tagsHtml += `<span class="tag tag-gt" title="Açıklama: ${alert.anomaly_reason_gt}">Referans</span>`;
        }

        const badgeClass = alert.confidence === "Yüksek" ? "badge-high" : (alert.confidence === "Orta" ? "badge-medium" : "badge-low");
        const detailsJson = encodeURIComponent(JSON.stringify(alert));

        tr.innerHTML = `
            <td><strong>${alert.date}</strong></td>
            <td>${formatCurrency(alert.total_cost)}</td>
            <td><div class="detected-tags">${tagsHtml}</div></td>
            <td><span style="color: var(--primary); font-weight: 500;">${alert.primary_service}</span></td>
            <td><span class="feed-badge ${badgeClass}">${alert.confidence}</span></td>
            <td><span class="root-cause-summary" style="display:inline-block; max-width: 350px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${alert.root_cause_explanation}">${alert.root_cause_explanation}</span></td>
            <td><button class="btn btn-outline btn-sm" onclick="showAttributionDetails('${detailsJson}')">Detaylar</button></td>
        `;
        tbody.appendChild(tr);
    });
}

// Doğruluk tablosu
function renderMetricsTable() {
    const tbody = document.getElementById("metrics-table-body");
    tbody.innerHTML = "";

    if (!metricsData.STL) return;

    const models = [
        { name: "STL Decomposition (Ayrıştırma)", key: "STL" },
        { name: "Isolation Forest (İzole Orman)", key: "IsolationForest" },
        { name: "Z-Score (Z-Skoru)", key: "ZScore" }
    ];

    models.forEach(m => {
        const metric = metricsData[m.key];
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td><strong>${m.name}</strong></td>
            <td style="color: var(--primary); font-weight: 600;">${(metric.precision * 100).toFixed(1)}%</td>
            <td style="color: var(--secondary); font-weight: 600;">${(metric.recall * 100).toFixed(1)}%</td>
            <td style="color: var(--positive); font-weight: 600;">${(metric.f1_score * 100).toFixed(1)}%</td>
            <td style="font-family: monospace; color: var(--text-muted);">Doğru Alarm (TP): ${metric.tp} | Yanlış Alarm (FP): ${metric.fp} | Kaçırılan (FN): ${metric.fn}</td>
        `;
        tbody.appendChild(tr);
    });
}

// Modal Kök Neden Detayları penceresi
window.showAttributionDetails = function(detailsJsonEncoded) {
    const alert = JSON.parse(decodeURIComponent(detailsJsonEncoded));
    
    let breakdownHtml = `<div class="breakdown-list" style="margin-top: 16px; text-align: left;">`;
    alert.breakdown.forEach(item => {
        const pct = item.contribution_pct.toFixed(1);
        breakdownHtml += `
            <div style="display:flex; justify-content:space-between; margin-bottom:8px; border-bottom:1px solid rgba(255,255,255,0.05); padding-bottom:4px;">
                <span><strong>${item.service}</strong>: ${formatCurrency(item.current_cost)} <span style="font-size:10px; color:var(--text-muted);">(Normal: ${formatCurrency(item.normal_cost)})</span></span>
                <span style="color:var(--negative); font-weight:600;">+%${pct} (${formatCurrency(item.spike_amount)})</span>
            </div>
        `;
    });
    breakdownHtml += `</div>`;

    let detectionLine = alert.detected_by.length > 0 ? 
        `Tespit Eden Modeller: <strong style="color: var(--primary);">${alert.detected_by.join(", ")}</strong>` : 
        `<span style="color: var(--text-muted);">Modeller tarafından yakalanamadı (Referans veri kayıtlarından alındı)</span>`;

    const content = `
        <div style="font-size: 13px; text-align: left; line-height: 1.5;">
            <p style="margin-bottom: 8px;">Tarih: <strong>${alert.date}</strong></p>
            <p style="margin-bottom: 8px;">Günlük Toplam Harcama: <strong>${formatCurrency(alert.total_cost)}</strong></p>
            <p style="margin-bottom: 8px;">${detectionLine}</p>
            <p style="margin-bottom: 8px;">Güven Derecesi: <span class="feed-badge ${alert.confidence === 'Yüksek' ? 'badge-high' : 'badge-medium'}">${alert.confidence}</span></p>
            <hr class="divider" style="margin: 12px 0;">
            <h4 style="color: var(--primary); margin-bottom: 6px;">Tespit Edilen Kök Neden Açıklaması:</h4>
            <p style="background: rgba(0,0,0,0.2); padding: 10px; border-radius: 6px; border-left: 3px solid var(--primary); margin-bottom: 16px;">${alert.root_cause_explanation}</p>
            <h4 style="margin-bottom: 6px;">Servis Bazlı Maliyet Sıçramaları:</h4>
            ${breakdownHtml}
        </div>
    `;

    showModal(`Kök Neden Analiz Detayları`, content);
};

// --- GRAFİK ÇİZİM FONKSİYONLARI ---

function renderCostTimelineChart() {
    if (costData.length === 0) return;

    const ctx = document.getElementById("costTimelineChart").getContext("2d");
    
    const labels = costData.map(d => d.date);
    const costs = costData.map(d => d.TotalCost);
    
    const showGT = document.getElementById("toggle-gt").checked;
    const showSTL = document.getElementById("toggle-stl").checked;
    const showIForest = document.getElementById("toggle-iforest").checked;
    const showZScore = document.getElementById("toggle-zscore").checked;

    const pointRadii = [];
    const pointBg = [];
    const pointBorder = [];
    const pointHoverRadii = [];

    for (let i = 0; i < costData.length; i++) {
        const item = costData[i];
        
        let isAnom = false;
        let color = '#00f0ff';
        let radius = 3;

        // Katman önceliği: Referans (GT) > STL > IForest > ZScore
        if (showZScore && item.zscore.is_anomaly) {
            isAnom = true;
            color = '#ffd600';
            radius = 6;
        }
        if (showIForest && item.iforest.is_anomaly) {
            isAnom = true;
            color = '#8a2be2';
            radius = 7;
        }
        if (showSTL && item.stl.is_anomaly) {
            isAnom = true;
            color = '#00f0ff';
            radius = 8;
        }
        if (showGT && item.is_anomaly_gt) {
            isAnom = true;
            color = '#ffffff';
            radius = 9;
        }

        if (isAnom) {
            pointRadii.push(radius);
            pointHoverRadii.push(radius + 2);
            pointBg.push(color);
            pointBorder.push('#0d0e1c');
        } else {
            pointRadii.push(0); // Düzgün çizgi için normal günlerde noktaları gizle
            pointHoverRadii.push(5);
            pointBg.push('rgba(0, 240, 255, 0.4)');
            pointBorder.push('transparent');
        }
    }

    if (charts.timeline) {
        charts.timeline.destroy();
    }

    charts.timeline = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Günlük Maliyet ($)',
                data: costs,
                borderColor: 'rgba(0, 240, 255, 0.65)',
                borderWidth: 2,
                backgroundColor: 'rgba(0, 240, 255, 0.05)',
                fill: true,
                tension: 0.15,
                pointRadius: pointRadii,
                pointHoverRadius: pointHoverRadii,
                pointBackgroundColor: pointBg,
                pointBorderColor: pointBorder,
                pointBorderWidth: 1.5
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false
            },
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    backgroundColor: 'rgba(13, 14, 28, 0.95)',
                    titleColor: '#00f0ff',
                    borderColor: 'rgba(255,255,255,0.08)',
                    borderWidth: 1,
                    padding: 12,
                    callbacks: {
                        labelColor: function() {
                            return {
                                borderColor: 'transparent',
                                backgroundColor: '#00f0ff'
                            };
                        },
                        afterBody: function(items) {
                            const index = items[0].dataIndex;
                            const item = costData[index];
                            let extraText = [];
                            
                            if (item.is_anomaly_gt) {
                                extraText.push(`[Referans] Gerçek Neden: ${item.anomaly_reason_gt}`);
                            }
                            
                            let detectors = [];
                            if (item.stl.is_anomaly) detectors.push("STL");
                            if (item.iforest.is_anomaly) detectors.push("I-Forest");
                            if (item.zscore.is_anomaly) detectors.push("Z-Score");
                            
                            if (detectors.length > 0) {
                                extraText.push(`Tespit Edenler: ${detectors.join(', ')}`);
                            }
                            
                            return extraText.join('\n');
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: {
                        color: 'rgba(255, 255, 255, 0.03)'
                    },
                    ticks: {
                        color: '#8b92b6',
                        maxTicksLimit: 12
                    }
                },
                y: {
                    grid: {
                        color: 'rgba(255, 255, 255, 0.03)'
                    },
                    ticks: {
                        color: '#8b92b6',
                        callback: function(value) {
                            return '$' + value;
                        }
                    }
                }
            }
        }
    });
}

function renderServiceSplitChart() {
    if (costData.length === 0) return;

    const ctx = document.getElementById("serviceSplitChart").getContext("2d");

    const services = ['AmazonEC2', 'AmazonRDS', 'AmazonS3', 'AmazonDynamoDB', 'AWSDataTransfer'];
    const serviceTotals = {
        'AmazonEC2': 0,
        'AmazonRDS': 0,
        'AmazonS3': 0,
        'AmazonDynamoDB': 0,
        'AWSDataTransfer': 0
    };

    costData.forEach(d => {
        services.forEach(s => {
            serviceTotals[s] += d.services[s] || 0;
        });
    });

    const labels = Object.keys(serviceTotals);
    const data = Object.values(serviceTotals);

    if (charts.serviceSplit) {
        charts.serviceSplit.destroy();
    }

    charts.serviceSplit = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{
                data: data,
                backgroundColor: [
                    '#00f0ff', // EC2
                    '#8a2be2', // RDS
                    '#00e676', // S3
                    '#ffd600', // DynamoDB
                    '#ff1744'  // DataTransfer
                ],
                borderColor: '#12131a',
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'right',
                    labels: {
                        color: '#8b92b6',
                        font: {
                            size: 11
                        },
                        padding: 12
                    }
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const val = context.raw;
                            const total = context.dataset.data.reduce((a, b) => a + b, 0);
                            const pct = ((val / total) * 100).toFixed(1);
                            return `${context.label}: ${formatCurrency(val)} (%${pct})`;
                        }
                    }
                }
            },
            cutout: '70%'
        }
    });
}

function renderMetricsChart() {
    if (!metricsData.STL) return;

    const ctx = document.getElementById("metricsComparisonChart").getContext("2d");

    const datasets = [
        {
            label: 'Kesinlik (Precision - Yanlış Alarm Önleme)',
            data: [
                metricsData.STL.precision,
                metricsData.IsolationForest.precision,
                metricsData.ZScore.precision
            ],
            backgroundColor: 'rgba(0, 240, 255, 0.65)',
            borderColor: '#00f0ff',
            borderWidth: 1
        },
        {
            label: 'Duyarlılık (Recall - Anomalileri Kaçırmama)',
            data: [
                metricsData.STL.recall,
                metricsData.IsolationForest.recall,
                metricsData.ZScore.recall
            ],
            backgroundColor: 'rgba(138, 43, 226, 0.65)',
            borderColor: '#8a2be2',
            borderWidth: 1
        },
        {
            label: 'F1-Skoru (Genel Model Başarısı)',
            data: [
                metricsData.STL.f1_score,
                metricsData.IsolationForest.f1_score,
                metricsData.ZScore.f1_score
            ],
            backgroundColor: 'rgba(0, 230, 118, 0.65)',
            borderColor: '#00e676',
            borderWidth: 1
        }
    ];

    if (charts.metrics) {
        charts.metrics.destroy();
    }

    charts.metrics = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: ['STL Decomposition', 'Isolation Forest', 'Z-Score (Rolling)'],
            datasets: datasets
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        color: '#8b92b6',
                        padding: 16
                    }
                }
            },
            scales: {
                x: {
                    grid: { color: 'rgba(255, 255, 255, 0.03)' },
                    ticks: { color: '#8b92b6' }
                },
                y: {
                    grid: { color: 'rgba(255, 255, 255, 0.03)' },
                    ticks: {
                        color: '#8b92b6',
                        callback: function(value) {
                            return (value * 100) + '%';
                        }
                    },
                    max: 1.0
                }
            }
        }
    });
}

function renderSTLDecompositionCharts() {
    if (costData.length === 0) return;

    const dates = costData.map(d => d.date);
    const trend = costData.map(d => d.stl.trend);
    const seasonal = costData.map(d => d.stl.seasonal);
    const resid = costData.map(d => d.stl.resid);

    const commonOptions = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
            x: {
                grid: { color: 'rgba(255, 255, 255, 0.02)' },
                ticks: { display: false }
            },
            y: {
                grid: { color: 'rgba(255, 255, 255, 0.02)' },
                ticks: { color: '#8b92b6', maxTicksLimit: 4 }
            }
        }
    };

    // 1. Trend
    const ctxTrend = document.getElementById("stlTrendChart").getContext("2d");
    if (charts.stlTrend) charts.stlTrend.destroy();
    charts.stlTrend = new Chart(ctxTrend, {
        type: 'line',
        data: {
            labels: dates,
            datasets: [{
                data: trend,
                borderColor: '#00f0ff',
                borderWidth: 1.5,
                pointRadius: 0
            }]
        },
        options: commonOptions
    });

    // 2. Mevsimsel
    const ctxSeasonal = document.getElementById("stlSeasonalChart").getContext("2d");
    if (charts.stlSeasonal) charts.stlSeasonal.destroy();
    charts.stlSeasonal = new Chart(ctxSeasonal, {
        type: 'line',
        data: {
            labels: dates,
            datasets: [{
                data: seasonal,
                borderColor: '#8a2be2',
                borderWidth: 1.5,
                pointRadius: 0
            }]
        },
        options: commonOptions
    });

    // 3. Artık (Residual)
    const ctxResid = document.getElementById("stlResidualChart").getContext("2d");
    if (charts.stlResidual) charts.stlResidual.destroy();
    
    const stlThreshold = params.stl_threshold;
    
    const residualsAbsolute = resid.map(v => Math.abs(v));
    const medianResid = median(resid);
    const mad = median(resid.map(v => Math.abs(v - medianResid))) || 1;
    
    const colors = resid.map(v => {
        return (Math.abs(v - medianResid) / mad > stlThreshold) ? '#ff1744' : 'rgba(255, 255, 255, 0.2)';
    });

    charts.stlResidual = new Chart(ctxResid, {
        type: 'bar',
        data: {
            labels: dates,
            datasets: [{
                data: resid,
                backgroundColor: colors,
                borderColor: 'transparent',
                barPercentage: 0.8
            }]
        },
        options: {
            ...commonOptions,
            scales: {
                x: {
                    grid: { color: 'rgba(255, 255, 255, 0.02)' },
                    ticks: { color: '#8b92b6', maxTicksLimit: 12 }
                },
                y: {
                    grid: { color: 'rgba(255, 255, 255, 0.02)' },
                    ticks: { color: '#8b92b6', maxTicksLimit: 4 }
                }
            }
        }
    });
}

// Yardımcı Medyan fonksiyonu
function median(values) {
    if (values.length === 0) return 0;
    const sorted = [...values].sort((a, b) => a - b);
    const half = Math.floor(sorted.length / 2);
    if (sorted.length % 2 !== 0) return sorted[half];
    return (sorted[half - 1] + sorted[half]) / 2.0;
}

// Modal penceresi tetikleyici
function showModal(title, messageHtml, onCloseCallback = null) {
    document.getElementById("modal-title").innerHTML = title;
    document.getElementById("modal-message").innerHTML = messageHtml;
    
    const overlay = document.getElementById("custom-modal");
    overlay.classList.add("active");

    const closeBtn = document.getElementById("btn-close-modal");
    
    const newClose = () => {
        hideModal();
        if (onCloseCallback) {
            onCloseCallback();
        }
        closeBtn.removeEventListener("click", newClose);
    };
    
    closeBtn.addEventListener("click", newClose);
}

function hideModal() {
    document.getElementById("custom-modal").classList.remove("active");
}

function triggerChartResize() {
    Object.values(charts).forEach(chart => {
        if (chart) {
            chart.resize();
        }
    });
}

function formatCurrency(val) {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(val);
}

// Precision-Recall (PR) Eğrisini Çizen Fonksiyon (Rapor Bölüm 5 İsteri)
function renderPRCurveChart(data) {
    if (!data.STL) return;

    const ctx = document.getElementById("prCurveChart").getContext("2d");

    // Noktaları x = recall, y = precision olacak şekilde biçimlendir
    const stlPoints = data.STL.map(d => ({ x: d.recall, y: d.precision, threshold: d.threshold }));
    const zscorePoints = data.ZScore.map(d => ({ x: d.recall, y: d.precision, threshold: d.threshold }));

    // Düzgün çizim için noktaları recall değerine göre sırala
    stlPoints.sort((a, b) => a.x - b.x);
    zscorePoints.sort((a, b) => a.x - b.x);

    if (charts.prCurve) {
        charts.prCurve.destroy();
    }

    charts.prCurve = new Chart(ctx, {
        type: 'line',
        data: {
            datasets: [
                {
                    label: 'STL Decomposition (PR Eğrisi)',
                    data: stlPoints,
                    borderColor: '#00f0ff',
                    backgroundColor: 'rgba(0, 240, 255, 0.05)',
                    borderWidth: 2,
                    showLine: true,
                    tension: 0.1,
                    pointRadius: 4,
                    pointHoverRadius: 6
                },
                {
                    label: 'Z-Score (PR Eğrisi)',
                    data: zscorePoints,
                    borderColor: '#ffd600',
                    backgroundColor: 'rgba(255, 214, 0, 0.05)',
                    borderWidth: 2,
                    showLine: true,
                    tension: 0.1,
                    pointRadius: 4,
                    pointHoverRadius: 6
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: { color: '#8b92b6', padding: 16 }
                },
                tooltip: {
                    callbacks: {
                        title: function() {
                            return 'Precision-Recall Noktası';
                        },
                        label: function(context) {
                            const point = context.raw;
                            const modelName = context.dataset.label.split(" ")[0];
                            return [
                                `Model: ${modelName}`,
                                `Eşik Değeri: ${point.threshold}`,
                                `Duyarlılık (Recall): %${(point.x * 100).toFixed(1)}`,
                                `Kesinlik (Precision): %${(point.y * 100).toFixed(1)}`
                            ];
                        }
                    }
                }
            },
            scales: {
                x: {
                    type: 'linear',
                    position: 'bottom',
                    title: {
                        display: true,
                        text: 'Duyarlılık (Recall / Kaçırmama Oranı)',
                        color: '#8b92b6',
                        font: { size: 12, weight: 'bold' }
                    },
                    grid: { color: 'rgba(255, 255, 255, 0.03)' },
                    ticks: {
                        color: '#8b92b6',
                        callback: function(value) { return (value * 100) + '%'; }
                    },
                    min: 0,
                    max: 1.05
                },
                y: {
                    title: {
                        display: true,
                        text: 'Kesinlik (Precision / Doğru Alarm Oranı)',
                        color: '#8b92b6',
                        font: { size: 12, weight: 'bold' }
                    },
                    grid: { color: 'rgba(255, 255, 255, 0.03)' },
                    ticks: {
                        color: '#8b92b6',
                        callback: function(value) { return (value * 100) + '%'; }
                    },
                    min: 0,
                    max: 1.05
                }
            }
        }
    });
}
