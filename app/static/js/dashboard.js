// Dashboard JavaScript for OPTCG Price Tracker
// All prices displayed in USD

let priceHistoryChart = null;
let comparisonChart = null;

async function initializeCharts(productId) {
    await updatePriceHistoryChart(productId);
    await updateComparisonChart(productId);
}

async function updatePriceHistoryChart(productId) {
    try {
        const response = await fetch(`/api/prices/${productId}?days=30`);
        const data = await response.json();

        const ctx = document.getElementById('priceHistoryChart').getContext('2d');

        if (priceHistoryChart) {
            priceHistoryChart.destroy();
        }

        priceHistoryChart = new Chart(ctx, {
            type: 'line',
            data: data,
            options: {
                responsive: true,
                scales: {
                    x: {
                        type: 'time',
                        time: {
                            unit: 'day'
                        },
                        title: {
                            display: true,
                            text: 'Date'
                        }
                    },
                    y: {
                        title: {
                            display: true,
                            text: 'Price (USD)'
                        },
                        beginAtZero: false,
                        ticks: {
                            callback: function(value) {
                                return '$' + value.toFixed(0);
                            }
                        }
                    }
                },
                plugins: {
                    legend: {
                        position: 'top'
                    },
                    tooltip: {
                        mode: 'index',
                        intersect: false,
                        callbacks: {
                            label: function(context) {
                                return context.dataset.label + ': $' + context.parsed.y.toFixed(2);
                            }
                        }
                    }
                },
                interaction: {
                    mode: 'nearest',
                    axis: 'x',
                    intersect: false
                }
            }
        });
    } catch (error) {
        console.error('Error loading price history chart:', error);
    }
}

async function updateComparisonChart(productId) {
    try {
        const response = await fetch(`/api/prices/compare?product_id=${productId}`);
        const data = await response.json();

        const ctx = document.getElementById('comparisonChart').getContext('2d');

        if (comparisonChart) {
            comparisonChart.destroy();
        }

        comparisonChart = new Chart(ctx, {
            type: 'bar',
            data: data,
            options: {
                responsive: true,
                scales: {
                    y: {
                        beginAtZero: false,
                        title: {
                            display: true,
                            text: 'Price (USD)'
                        },
                        ticks: {
                            callback: function(value) {
                                return '$' + value.toFixed(0);
                            }
                        }
                    }
                },
                plugins: {
                    legend: {
                        display: false
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                return '$' + context.parsed.y.toFixed(2);
                            }
                        }
                    }
                }
            }
        });
    } catch (error) {
        console.error('Error loading comparison chart:', error);
    }
}

async function loadTablePrices() {
    // Get unique product IDs from table
    const productIds = new Set();
    document.querySelectorAll('.price-cell').forEach(cell => {
        productIds.add(cell.dataset.product);
    });

    // Fetch prices for each product
    for (const productId of productIds) {
        try {
            const response = await fetch(`/api/products/${productId}/latest`);
            const data = await response.json();

            // Update cells for this product
            const cells = document.querySelectorAll(`.price-cell[data-product="${productId}"]`);
            cells.forEach(cell => {
                const retailerId = parseInt(cell.dataset.retailer);
                const price = data.prices.find(p => p.retailer_id === retailerId);

                if (price) {
                    // All prices now in USD
                    cell.innerHTML = '$' + price.price.toFixed(2);
                    if (!price.in_stock) {
                        cell.classList.add('text-muted');
                        cell.innerHTML += ' <small>(OOS)</small>';
                    }
                } else {
                    cell.innerHTML = '<span class="text-muted">-</span>';
                }
            });

            // Update best price
            updateBestPrice(productId, data.prices);

        } catch (error) {
            console.error(`Error loading prices for product ${productId}:`, error);
        }
    }
}

function updateBestPrice(productId, prices) {
    const bestPriceCell = document.querySelector(`.best-price[data-product="${productId}"]`);
    if (!bestPriceCell || !prices || prices.length === 0) return;

    // Filter in-stock items
    const inStock = prices.filter(p => p.in_stock);
    const pricesToConsider = inStock.length > 0 ? inStock : prices;

    // Find minimum price (all prices now in USD)
    const best = pricesToConsider.reduce((min, p) =>
        p.price < min.price ? p : min
    );

    bestPriceCell.innerHTML = '$' + best.price.toFixed(2);
    bestPriceCell.title = `Best from ${best.retailer}`;

    // Highlight the best price cell in the row
    const row = bestPriceCell.closest('tr');
    if (row) {
        row.querySelectorAll('.price-cell').forEach(cell => {
            cell.classList.remove('table-success', 'fw-bold');
        });
        const bestCell = row.querySelector(`.price-cell[data-retailer="${best.retailer_id}"]`);
        if (bestCell) {
            bestCell.classList.add('table-success', 'fw-bold');
        }
    }
}
