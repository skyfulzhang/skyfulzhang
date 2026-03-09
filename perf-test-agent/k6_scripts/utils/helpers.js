/**
 * k6_scripts/utils/helpers.js
 * k6 公共辅助函数库 - 在各模板中通过本地导入使用
 */
import { check } from 'k6';
import { Rate, Trend } from 'k6/metrics';

// ── 公共指标 ──────────────────────────────────────────────────────────────────
export const sharedErrorRate = new Rate('shared_error_rate');
export const sharedResponseTime = new Trend('shared_response_time', true);

/**
 * 带重试的 HTTP GET 请求
 * @param {string} url - 请求 URL
 * @param {object} params - k6 请求参数
 * @param {number} maxRetries - 最大重试次数（默认 3）
 * @returns {object} k6 Response 对象
 */
export function getWithRetry(url, params, maxRetries = 3) {
  import { sleep } from 'k6';
  let res;
  for (let i = 0; i < maxRetries; i++) {
    res = http.get(url, params);
    if (res.status < 500) break;
    sleep(Math.pow(2, i) * 0.5);  // 指数退避
  }
  return res;
}

/**
 * 标准健康检查
 * @param {string} baseUrl - 目标 base URL
 * @param {object} params - k6 请求参数
 * @returns {boolean} 健康检查是否通过
 */
export function healthCheck(baseUrl, params) {
  const res = http.get(`${baseUrl}/health`, { ...params, timeout: '5s' });
  return check(res, {
    'health check passed': (r) => r.status === 200,
  });
}

/**
 * 解析 JSON 响应体，失败时返回 null
 * @param {object} res - k6 Response 对象
 * @returns {object|null} 解析后的 JSON 对象
 */
export function parseJSON(res) {
  try {
    return res.json();
  } catch (e) {
    return null;
  }
}

/**
 * 生成随机字符串（用于测试数据）
 * @param {number} length - 字符串长度
 * @returns {string} 随机字符串
 */
export function randomString(length = 8) {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  let result = '';
  for (let i = 0; i < length; i++) {
    result += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return result;
}

/**
 * 生成随机整数
 * @param {number} min - 最小值（含）
 * @param {number} max - 最大值（含）
 * @returns {number}
 */
export function randomInt(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

/**
 * 记录请求结果到自定义指标
 * @param {object} res - k6 Response 对象
 * @param {object} checks - check 条件字典
 */
export function recordMetrics(res, checks) {
  const success = check(res, checks);
  sharedErrorRate.add(!success);
  sharedResponseTime.add(res.timings.duration);
  return success;
}

/**
 * 构建认证请求头
 * @param {string} token - Bearer Token
 * @returns {object} 请求头对象
 */
export function authHeaders(token) {
  return {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json',
    'Accept': 'application/json',
  };
}
