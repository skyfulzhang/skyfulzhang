/**
 * K6 Stress Test Template
 * Test Type: Stress Test（压力测试 - 超过正常容量）
 *
 * 测试策略：
 * - 逐步增加负载，直到超过系统设计容量
 * - 观察系统在超负荷下的表现（降级、错误、崩溃点）
 * - 找到系统的实际承载上限
 *
 * 用途：识别系统断点，验证错误处理和恢复能力
 */
import http from 'k6/http';
import { sleep, check, group } from 'k6';
import { Rate, Trend } from 'k6/metrics';
import { htmlReport } from 'https://raw.githubusercontent.com/benc-uk/k6-reporter/main/dist/bundle.js';
import { textSummary } from 'https://jslib.k6.io/k6-summary/0.0.1/index.js';

const errorRate = new Rate('custom_error_rate');
const responseTime = new Trend('custom_response_time', true);

const BASE_URL = __ENV.K6_BASE_URL || '{{BASE_URL}}';
const TEST_NAME = __ENV.K6_TEST_NAME || '{{TEST_NAME}}';
const BASE_VUS = parseInt(__ENV.K6_VUS || '{{VUS}}');

export const options = {
  // 压力测试：逐步超越正常容量，然后恢复
  stages: [
    { duration: '2m', target: BASE_VUS },          // 预热到正常负载
    { duration: '5m', target: BASE_VUS },           // 维持正常负载
    { duration: '2m', target: BASE_VUS * 2 },       // 增加到 2x 负载
    { duration: '5m', target: BASE_VUS * 2 },       // 维持 2x 负载
    { duration: '2m', target: BASE_VUS * 3 },       // 增加到 3x 负载（压力峰值）
    { duration: '5m', target: BASE_VUS * 3 },       // 维持压力峰值
    { duration: '5m', target: 0 },                  // 恢复阶段
  ],
  // 压力测试允许更高的错误率和响应时间
  thresholds: {
    'http_req_duration': ['p(95)<2000', 'p(99)<5000'],
    'http_req_failed': ['rate<0.10'],               // 允许 10% 错误率
    'custom_error_rate': ['rate<0.15'],
  },
  ext: {
    loadimpact: { name: TEST_NAME },
  },
};

const params = {
  headers: {
    'Content-Type': 'application/json',
    'User-Agent': 'K6-StressTest/1.0',
  },
  timeout: '60s',   // 压力下响应可能更慢
};

export default function () {
  group('Stress Test - Main Flow', () => {
    const res = http.get(`${BASE_URL}/`, params);

    const success = check(res, {
      'status is 2xx': (r) => r.status >= 200 && r.status < 300,
      'no server error': (r) => r.status < 500,
    });

    errorRate.add(!success);
    responseTime.add(res.timings.duration);
  });

  // 压力测试中减少 sleep，增加并发压力
  sleep(0.5);
}

export function handleSummary(data) {
  const reportDir = __ENV.REPORT_DIR || './reports';
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);

  return {
    [`${reportDir}/${TEST_NAME}_${timestamp}_report.html`]: htmlReport(data),
    [`${reportDir}/${TEST_NAME}_${timestamp}_summary.json`]: JSON.stringify(data, null, 2),
    'stdout': textSummary(data, { indent: ' ', enableColors: true }),
  };
}
