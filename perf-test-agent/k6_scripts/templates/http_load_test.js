/**
 * K6 HTTP Load Test Template
 * Test Type: Load Test（正常负载测试）
 *
 * 测试阶段：
 * - 爬升期 (Ramp-up): 逐步增加到目标 VU 数
 * - 稳定期 (Steady State): 维持目标负载
 * - 下降期 (Ramp-down): 逐步减少 VU
 *
 * 用途：验证系统在预期负载下的性能表现
 */
import http from 'k6/http';
import { sleep, check, group } from 'k6';
import { Rate, Trend, Counter } from 'k6/metrics';
import { htmlReport } from 'https://raw.githubusercontent.com/benc-uk/k6-reporter/main/dist/bundle.js';
import { textSummary } from 'https://jslib.k6.io/k6-summary/0.0.1/index.js';

// 自定义指标
const errorRate = new Rate('custom_error_rate');
const responseTime = new Trend('custom_response_time', true);
const successCount = new Counter('custom_success_count');

// 环境变量配置（支持通过 -e 参数或 GitHub Actions 注入）
const BASE_URL = __ENV.K6_BASE_URL || '{{BASE_URL}}';
const TEST_NAME = __ENV.K6_TEST_NAME || '{{TEST_NAME}}';
const VUS = parseInt(__ENV.K6_VUS || '{{VUS}}');
const DURATION = __ENV.K6_DURATION || '{{DURATION}}';
const RAMP_UP = __ENV.RAMP_UP || '{{RAMP_UP}}';
const RAMP_DOWN = __ENV.RAMP_DOWN || '{{RAMP_DOWN}}';

export const options = {
  // 三阶段负载配置
  stages: [
    { duration: RAMP_UP, target: VUS },       // 爬升期
    { duration: DURATION, target: VUS },       // 稳定期
    { duration: RAMP_DOWN, target: 0 },        // 下降期
  ],
  // 性能阈值（未通过则 workflow 以非零退出）
  thresholds: {{THRESHOLDS}},
  // k6 Cloud / Grafana 显示名称
  ext: {
    loadimpact: {
      name: TEST_NAME,
    },
  },
};

// HTTP 请求默认参数
const params = {
  headers: {
    'Content-Type': 'application/json',
    'User-Agent': 'K6-PerfTest/1.0',
    ...{{HEADERS}},
  },
  timeout: '30s',
};

/**
 * 主测试函数 - 每个 VU 循环执行
 */
export default function () {
  // 使用 group 组织测试逻辑，便于报告中分类展示
  group('API Health Check', () => {
    const res = http.get(`${BASE_URL}/`, params);

    const success = check(res, {
      'status is 200': (r) => r.status === 200,
      'response time < 500ms': (r) => r.timings.duration < 500,
      'response has body': (r) => r.body && r.body.length > 0,
    });

    // 记录自定义指标
    errorRate.add(!success);
    responseTime.add(res.timings.duration);
    if (success) successCount.add(1);
  });

  // 思考时间：模拟真实用户行为，避免过度压测
  sleep(1);
}

/**
 * handleSummary - k6 内置钩子，测试结束后生成报告
 * 同时生成 HTML 和 JSON 两种格式
 */
export function handleSummary(data) {
  const reportDir = __ENV.REPORT_DIR || './reports';
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);

  return {
    [`${reportDir}/${TEST_NAME}_${timestamp}_report.html`]: htmlReport(data),
    [`${reportDir}/${TEST_NAME}_${timestamp}_summary.json`]: JSON.stringify(data, null, 2),
    'stdout': textSummary(data, { indent: ' ', enableColors: true }),
  };
}
