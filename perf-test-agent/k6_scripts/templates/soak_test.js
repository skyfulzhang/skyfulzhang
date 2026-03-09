/**
 * K6 Soak Test Template
 * Test Type: Soak Test（浸泡测试 - 长时间稳定负载）
 *
 * 测试策略：
 * - 在较低但稳定的负载下长时间运行（数小时）
 * - 检测内存泄漏、连接池耗尽、资源积累等问题
 * - 验证系统的长期稳定性
 *
 * 用途：发现只有在长时间运行才会出现的问题
 */
import http from 'k6/http';
import { sleep, check, group } from 'k6';
import { Rate, Trend, Counter } from 'k6/metrics';
import { htmlReport } from 'https://raw.githubusercontent.com/benc-uk/k6-reporter/main/dist/bundle.js';
import { textSummary } from 'https://jslib.k6.io/k6-summary/0.0.1/index.js';

const errorRate = new Rate('custom_error_rate');
const responseTime = new Trend('custom_response_time', true);
const requestCount = new Counter('total_requests');

const BASE_URL = __ENV.K6_BASE_URL || '{{BASE_URL}}';
const TEST_NAME = __ENV.K6_TEST_NAME || '{{TEST_NAME}}';
// 浸泡测试使用较低的并发数，关注稳定性而非极限
const SOAK_VUS = Math.max(parseInt(__ENV.K6_VUS || '{{VUS}}'), 5);
// 默认浸泡测试时长 2 小时（可通过环境变量覆盖）
const SOAK_DURATION = __ENV.K6_DURATION || '{{DURATION}}';

export const options = {
  stages: [
    { duration: '5m', target: SOAK_VUS },          // 缓慢爬升
    { duration: SOAK_DURATION, target: SOAK_VUS }, // 长时间稳定浸泡（关键阶段）
    { duration: '5m', target: 0 },                 // 结束
  ],
  thresholds: {
    'http_req_duration': ['p(95)<500', 'p(99)<1000'],
    'http_req_failed': ['rate<0.01'],
    'custom_error_rate': ['rate<0.01'],
    // 浸泡测试特有：监控响应时间是否随时间退化
    'http_req_duration{type:trend}': ['p(95)<600'],
  },
  ext: {
    loadimpact: { name: TEST_NAME },
  },
};

const params = {
  headers: {
    'Content-Type': 'application/json',
    'User-Agent': 'K6-SoakTest/1.0',
  },
  timeout: '30s',
};

export default function () {
  group('Soak Test - Stability Check', () => {
    const res = http.get(`${BASE_URL}/`, params);

    const success = check(res, {
      'status is 200': (r) => r.status === 200,
      'response time < 1s': (r) => r.timings.duration < 1000,
      'body not empty': (r) => r.body && r.body.length > 0,
    });

    errorRate.add(!success);
    responseTime.add(res.timings.duration);
    requestCount.add(1);
  });

  // 浸泡测试使用较长 sleep，维持稳定低负载
  sleep(2);
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
