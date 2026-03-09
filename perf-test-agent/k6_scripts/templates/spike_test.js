/**
 * K6 Spike Test Template
 * Test Type: Spike Test（尖峰测试 - 突发流量）
 *
 * 测试策略：
 * - 在极短时间内产生大量突发流量
 * - 模拟促销活动、突发新闻等场景
 * - 验证系统的弹性扩缩容和降级能力
 *
 * 用途：测试系统对突然高峰流量的应对能力
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
const NORMAL_VUS = parseInt(__ENV.K6_VUS || '{{VUS}}');
const SPIKE_VUS = NORMAL_VUS * 10;   // 尖峰流量为正常的 10 倍

export const options = {
  stages: [
    { duration: '10s', target: NORMAL_VUS },      // 热身：正常负载
    { duration: '1m', target: NORMAL_VUS },        // 维持正常负载
    { duration: '10s', target: SPIKE_VUS },        // ⚡ 快速爬升到尖峰（关键）
    { duration: '3m', target: SPIKE_VUS },         // 维持尖峰
    { duration: '10s', target: NORMAL_VUS },       // 快速恢复
    { duration: '3m', target: NORMAL_VUS },        // 正常负载下的恢复验证
    { duration: '10s', target: 0 },               // 结束
  ],
  thresholds: {
    'http_req_duration': ['p(95)<3000'],           // 尖峰时允许更高延迟
    'http_req_failed': ['rate<0.15'],              // 允许 15% 错误
  },
  ext: {
    loadimpact: { name: TEST_NAME },
  },
};

const params = {
  headers: {
    'Content-Type': 'application/json',
    'User-Agent': 'K6-SpikeTest/1.0',
  },
  timeout: '30s',
};

export default function () {
  group('Spike Test', () => {
    const res = http.get(`${BASE_URL}/`, params);

    const success = check(res, {
      'status is not 5xx': (r) => r.status < 500,
      'response time < 5s': (r) => r.timings.duration < 5000,
    });

    errorRate.add(!success);
    responseTime.add(res.timings.duration);
  });

  sleep(1);
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
