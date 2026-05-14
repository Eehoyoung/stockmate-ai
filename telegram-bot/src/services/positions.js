'use strict';

const { Pool } = require('pg');

let pool = null;

function getPool() {
    if (pool) return pool;

    pool = new Pool({
        host: process.env.POSTGRES_HOST ?? 'localhost',
        port: Number(process.env.POSTGRES_PORT ?? 5432),
        database: process.env.POSTGRES_DB ?? 'SMA',
        user: process.env.POSTGRES_USER ?? 'postgres',
        password: process.env.POSTGRES_PASSWORD ?? '',
        max: 5,
        idleTimeoutMillis: 10_000,
    });

    return pool;
}

async function getActivePositions() {
    const { rows } = await getPool().query(
        `SELECT
                id,
                stk_cd,
                stk_nm,
                strategy,
                entry_price,
                COALESCE(tp1_price, target_price) AS tp1_price,
                COALESCE(sl_price, stop_price) AS sl_price,
                COALESCE(entry_at, executed_at, created_at) AS buy_at,
                signal_status,
                position_status
           FROM trading_signals
          WHERE position_status IN ('ACTIVE', 'PARTIAL_TP', 'OVERNIGHT')
            AND COALESCE(monitor_enabled, TRUE) = TRUE
            AND COALESCE(signal_status, 'PENDING') IN ('PENDING', 'SENT', 'EXECUTED', 'OVERNIGHT_HOLD')
            AND exit_type IS NULL
          ORDER BY COALESCE(entry_at, executed_at, created_at), stk_cd`,
    );
    return rows;
}

async function close() {
    if (pool) {
        await pool.end();
        pool = null;
    }
}

module.exports = {
    close,
    getActivePositions,
};
