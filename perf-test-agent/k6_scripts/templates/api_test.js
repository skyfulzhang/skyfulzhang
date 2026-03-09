/**
 * K6 API Test Template
 * Test Type: API Functional + Performance Test（API 端到端功能+性能测试）
 *
 * 测试策略：
 * - 模拟完整的 API 业务流程（CRUD）
 * - 同时验证功能正确性和性能指标
 * - 使用 scenarios 实现多场景并发
 *
 * 用途：回归测试、发布前验证
 */
import http from 'k6/http';
import { sleep, check, group } from 'k6';
import { Rate, Trend } from 'k6/metrics';
import { htmlReport } from 'https://raw.githubusercontent.com/benc-uk/k6-reporter/main/dist/bundle.js';
import { textSummary } from 'https://jslib.k6.io/k6-summary/0.0.1/index.js';

// 功能正确性指标
const functionalErrorRate = new Rate('functional_errors');
// 各接口独立响应时间指标
const getResponseTime = new Trend('api_get_response', true);
const postResponseTime = new Trend('api_post_response', true);

const BASE_URL = __ENV.K6_BASE_URL || '{{BASE_URL}}';
const TEST_NAME = __ENV.K6_TEST_NAME || '{{TEST_NAME}}';
const VUS = parseInt(__ENV.K6_VUS || '{{VUS}}');

export const options = {
  // 使用 scenarios 实现多场景测试
  scenarios: {
    // 场景 1：只读 API（读多写少）
    read_api: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: VUS },
        { duration: '{{DURATION}}', target: VUS },
        { duration: '10s', target: 0 },
      ],
      gracefulRampDown: '30s',
      exec: 'readScenario',
    },
    // 场景 2：写入 API（较低并发）
    write_api: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: Math.max(1, Math.floor(VUS / 5)) },
        { duration: '{{DURATION}}', target: Math.max(1, Math.floor(VUS / 5)) },
        { duration: '10s', target: 0 },
      ],
      gracefulRampDown: '30s',
      exec: 'writeScenario',
    },
  },
  thresholds: {
    'http_req_duration': ['p(95)<500', 'p(99)<1000'],
    'http_req_failed': ['rate<0.01'],
    'functional_errors': ['rate<0.01'],             // 功能错误率
    'api_get_response': ['p(95)<300'],              // GET 接口更严格
    'api_post_response': ['p(95)<800'],             // POST 接口相对宽松
  },
  ext: {
    loadimpact: { name: TEST_NAME },
  },
};

const jsonHeaders = {
  'Content-Type': 'application/json',
  'Accept': 'application/json',
  'User-Agent': 'K6-APITest/1.0',
};

/**
 * 只读场景：GET 请求测试
 */
export function readScenario() {
  group('Read API', () => {
    // GET 列表
    const listRes = http.get(`${BASE_URL}/`, { headers: jsonHeaders, timeout: '10s' });
    const listOk = check(listRes, {
      'GET list - status 200': (r) => r.status === 200,
      'GET list - has response': (r) => r.body && r.body.length > 0,
      'GET list - fast response': (r) => r.timings.duration < 300,
    });
    getResponseTime.add(listRes.timings.duration);
    functionalErrorRate.add(!listOk);
  });

  sleep(1);
}

/**
 * 写入场景：POST 请求测试
 */
export function writeScenario() {
  group('Write API', () => {
    const payload = JSON.stringify({
      name: `test-${Date.now()}`,
      timestamp: new Date().toISOString(),
    });

    const postRes = http.post(
      `${BASE_URL}/`,
      payload,
      { headers: jsonHeaders, timeout: '15s' }
    );

    const postOk = check(postRes, {
      'POST - status 2xx': (r) => r.status >= 200 && r.status < 300,
      'POST - not server error': (r) => r.status < 500,
    });

    postResponseTime.add(postRes.timings.duration);
    functionalErrorRate.add(!postOk);
  });

  sleep(2);
}

/**
 * 默认导出函数（fallback，当直接运行不指定 scenario 时使用）
 */
export default function () {
  readScenario();
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
