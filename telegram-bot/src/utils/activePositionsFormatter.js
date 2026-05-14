'use strict';

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

function toFiniteNumber(value) {
    if (value == null || value === '') return null;
    const parsed = Number(String(value).replace(/,/g, ''));
    return Number.isFinite(parsed) ? parsed : null;
}

function formatWon(value) {
    const numeric = toFiniteNumber(value);
    return numeric == null || numeric <= 0 ? '-' : `${Math.round(numeric).toLocaleString()}원`;
}

function formatKstTime(value = new Date()) {
    return new Intl.DateTimeFormat('ko-KR', {
        timeZone: 'Asia/Seoul',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
    }).format(value);
}

function formatKstYymmdd(value) {
    if (!value) return '-';
    const date = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(date.getTime())) return '-';

    const parts = new Intl.DateTimeFormat('en-CA', {
        timeZone: 'Asia/Seoul',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
    }).formatToParts(date);
    const byType = Object.fromEntries(parts.map((part) => [part.type, part.value]));
    return `${byType.year.slice(-2)}${byType.month}${byType.day}`;
}

function formatActivePositionsMessage(positions, now = new Date()) {
    const rows = Array.isArray(positions) ? positions : [];
    const lines = [
        `<b>[활성 종목 현황] ${formatKstTime(now)} KST</b>`,
        `현재 활성 포지션: <b>${rows.length}</b>개`,
    ];

    if (rows.length === 0) {
        lines.push('', '현재 활성화된 종목이 없습니다.');
        return lines.join('\n');
    }

    lines.push('');
    rows.forEach((row, index) => {
        const stock = row.stk_nm
            ? `${escapeHtml(row.stk_nm)}(${escapeHtml(row.stk_cd)})`
            : escapeHtml(row.stk_cd);
        lines.push(
            `${index + 1}. <b>${stock}</b>`,
            `매수단가: <b>${formatWon(row.entry_price)}</b> | 1차목표가: <b>${formatWon(row.tp1_price)}</b> | 손절가: <b>${formatWon(row.sl_price)}</b> | 매수일: <b>${formatKstYymmdd(row.buy_at)}</b>`,
        );
    });

    return lines.join('\n');
}

module.exports = {
    formatActivePositionsMessage,
    formatKstYymmdd,
};
