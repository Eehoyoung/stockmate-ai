'use strict';

/**
 * ecosystem.config.js – PM2 프로세스 설정
 *
 * 사용법:
 *   pm2 start ecosystem.config.js   # 전체 서비스 시작
 *   pm2 stop all                     # 전체 중지
 *   pm2 restart all                  # 전체 재시작
 *   pm2 logs                         # 통합 로그
 *   pm2 startup && pm2 save          # 서버 재부팅 시 자동 시작 등록
 */

const path = require('path');
const root  = __dirname;

module.exports = {
  apps: [
    // ── 1. Python websocket-listener ──────────────────────────────
    {
      name:          'ws-listener',
      script:        'main.py',
      interpreter:   'python',
      cwd:           path.join(root, 'websocket-listener'),
      restart_delay: 5000,
      max_restarts:  20,
      watch:         false,
      env: {
        LOG_LEVEL: 'INFO',
      },
    },

    // ── 2. Python ai-engine ───────────────────────────────────────
    {
      name:          'ai-engine',
      script:        'engine.py',
      interpreter:   'python',
      cwd:           path.join(root, 'ai-engine'),
      restart_delay: 5000,
      max_restarts:  20,
      watch:         false,
      env: {
        LOG_LEVEL:                 'INFO',
        ENABLE_OVERNIGHT_WORKER:   'true',
      },
    },

    // ── 3. Node.js telegram-bot ───────────────────────────────────
    {
      name:          'telegram-bot',
      script:        'src/index.js',
      interpreter:   'node',
      cwd:           path.join(root, 'telegram-bot'),
      restart_delay: 3000,
      max_restarts:  20,
      watch:         false,
    },
  ],
};
