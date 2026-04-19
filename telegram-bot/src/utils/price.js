'use strict';

function getTickSize(price) {
    const value = Number(price ?? 0);
    if (value < 2000) return 1;
    if (value < 5000) return 5;
    if (value < 20000) return 10;
    if (value < 50000) return 50;
    if (value < 200000) return 100;
    if (value < 500000) return 500;
    return 1000;
}

function roundToTick(price, direction = 'nearest') {
    const value = Number(price ?? 0);
    if (!Number.isFinite(value) || value <= 0) return 0;
    const tick = getTickSize(value);
    if (direction === 'down') return Math.floor(value / tick) * tick;
    if (direction === 'up') return Math.ceil(value / tick) * tick;
    return Math.round(value / tick) * tick;
}

function normalizeForDisplay(price) {
    return roundToTick(price, 'nearest');
}

module.exports = {
    getTickSize,
    roundToTick,
    normalizeForDisplay,
};
