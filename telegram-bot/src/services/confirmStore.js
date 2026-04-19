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

function isExpired(row) {
    return !row || !row.expires_at || new Date(row.expires_at).getTime() <= Date.now();
}

async function getConfirmRequest(requestKey) {
    const { rows } = await getPool().query(
        `SELECT id, request_key, signal_id, stk_cd, stk_nm, strategy, rule_score, rr_ratio,
                status, payload, requested_at, expires_at, decided_at,
                decision_chat_id, decision_message_id, last_sent_at, last_enqueued_at,
                ai_score, ai_action, ai_confidence, ai_reason
           FROM human_confirm_requests
          WHERE request_key = $1`,
        [requestKey],
    );
    return rows[0] ?? null;
}

async function listActiveConfirmRequests(limit = 10) {
    const { rows } = await getPool().query(
        `SELECT request_key, stk_cd, stk_nm, strategy, status, rule_score, requested_at, expires_at
           FROM human_confirm_requests
          WHERE expires_at > NOW()
          ORDER BY requested_at DESC
          LIMIT $1`,
        [limit],
    );
    return rows;
}

async function markConfirmRequestSent(requestKey, chatId, messageId) {
    await getPool().query(
        `UPDATE human_confirm_requests
            SET last_sent_at = NOW(),
                decision_chat_id = COALESCE($2, decision_chat_id),
                decision_message_id = COALESCE($3, decision_message_id)
          WHERE request_key = $1`,
        [requestKey, chatId ? String(chatId) : null, messageId ?? null],
    );
}

async function approveConfirmRequest(requestKey, chatId, messageId) {
    const client = await getPool().connect();
    try {
        await client.query('BEGIN');
        const { rows } = await client.query(
            `SELECT request_key, status, payload, expires_at
               FROM human_confirm_requests
              WHERE request_key = $1
              FOR UPDATE`,
            [requestKey],
        );
        const row = rows[0];
        if (!row) {
            await client.query('ROLLBACK');
            return { ok: false, reason: 'not_found' };
        }
        if (isExpired(row)) {
            await client.query(
                `UPDATE human_confirm_requests
                    SET status = 'EXPIRED'
                  WHERE request_key = $1`,
                [requestKey],
            );
            await client.query('COMMIT');
            return { ok: false, reason: 'expired' };
        }
        if (row.status !== 'PENDING') {
            await client.query('ROLLBACK');
            return { ok: false, reason: row.status.toLowerCase() };
        }

        await client.query(
            `UPDATE human_confirm_requests
                SET status = 'APPROVED',
                    decided_at = NOW(),
                    decision_chat_id = COALESCE($2, decision_chat_id),
                    decision_message_id = COALESCE($3, decision_message_id),
                    last_enqueued_at = NOW()
              WHERE request_key = $1`,
            [requestKey, chatId ? String(chatId) : null, messageId ?? null],
        );
        await client.query('COMMIT');
        return { ok: true, payload: row.payload };
    } catch (e) {
        await client.query('ROLLBACK');
        throw e;
    } finally {
        client.release();
    }
}

async function rejectConfirmRequest(requestKey, chatId, messageId) {
    const { rowCount } = await getPool().query(
        `UPDATE human_confirm_requests
            SET status = CASE WHEN expires_at <= NOW() THEN 'EXPIRED' ELSE 'REJECTED' END,
                decided_at = NOW(),
                decision_chat_id = COALESCE($2, decision_chat_id),
                decision_message_id = COALESCE($3, decision_message_id)
          WHERE request_key = $1
            AND status = 'PENDING'`,
        [requestKey, chatId ? String(chatId) : null, messageId ?? null],
    );
    return rowCount > 0;
}

async function buildReanalysisPayload(requestKey) {
    const row = await getConfirmRequest(requestKey);
    if (!row) {
        return { ok: false, reason: 'not_found' };
    }
    if (isExpired(row)) {
        return { ok: false, reason: 'expired' };
    }

    const payload = {
        ...(row.payload || {}),
        confirm_request_key: row.request_key,
        recompute_rule_score: true,
        human_confirmed: true,
    };

    await getPool().query(
        `UPDATE human_confirm_requests
            SET status = 'APPROVED',
                last_enqueued_at = NOW()
          WHERE request_key = $1`,
        [requestKey],
    );

    return { ok: true, payload, row };
}

async function close() {
    if (pool) {
        await pool.end();
        pool = null;
    }
}

module.exports = {
    approveConfirmRequest,
    buildReanalysisPayload,
    close,
    getConfirmRequest,
    listActiveConfirmRequests,
    markConfirmRequestSent,
    rejectConfirmRequest,
};
