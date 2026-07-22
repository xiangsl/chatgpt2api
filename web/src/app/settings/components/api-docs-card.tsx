"use client";

import { useEffect, useState } from "react";
import { ChevronDown, FileArchive, FileJson, FileText, KeyRound, ListChecks, type LucideIcon } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import webConfig from "@/constants/common-env";
import { getStoredAuthSession } from "@/store/auth";

type ParamRow = [string, string, string];

type ApiDoc = {
  title: string;
  method: string;
  path: string;
  icon: LucideIcon;
  input: ParamRow[];
  output: ParamRow[];
  example: (baseUrl: string, key: string) => string;
};

const docs: ApiDoc[] = [
  {
    title: "模型列表",
    method: "GET",
    path: "/v1/models",
    icon: ListChecks,
    input: [
      ["Authorization", "header", "Bearer <auth-key>。"],
    ],
    output: [
      ["data", "array", "模型列表，包含 id、object、created、owned_by。"],
    ],
    example: (baseUrl: string, key: string) => `curl ${baseUrl}/models \\
  -H "Authorization: Bearer ${key}"`,
  },
  {
    title: "聊天补全",
    method: "POST",
    path: "/v1/chat/completions",
    icon: FileText,
    input: [
      ["model", "string", "模型名，例如 gpt-5-mini，也可用于图片兼容场景。"],
      ["messages", "array", "OpenAI 兼容消息数组。"],
      ["stream", "boolean", "可选，是否流式返回。"],
      ["n", "number", "可选，图片兼容场景会解析为生成数量。"],
    ],
    output: [
      ["id", "string", "响应 ID。"],
      ["choices", "array", "OpenAI 兼容 choices。"],
      ["usage", "object", "可选，token 使用信息。"],
    ],
    example: (baseUrl: string, key: string) => `curl ${baseUrl}/chat/completions \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer ${key}" \\
  -d '{"model":"gpt-5-mini","messages":[{"role":"user","content":"你好"}]}'`,
  },
  {
    title: "Responses",
    method: "POST",
    path: "/v1/responses",
    icon: FileText,
    input: [
      ["model", "string", "模型名。"],
      ["input", "string | array | object", "用户输入，图片生成会从中解析提示词。"],
      ["tools", "array", "可选，Responses 工具定义。"],
      ["stream", "boolean", "可选，是否流式返回。"],
    ],
    output: [
      ["id", "string", "响应 ID。"],
      ["output", "array", "Responses 兼容输出。"],
      ["status", "string", "响应状态。"],
    ],
    example: (baseUrl: string, key: string) => `curl ${baseUrl}/responses \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer ${key}" \\
  -d '{"model":"gpt-5-mini","input":"生成一张未来城市图片"}'`,
  },
  {
    title: "搜索",
    method: "POST",
    path: "/v1/search",
    icon: ListChecks,
    input: [
      ["prompt", "string", "搜索问题或检索指令。"],
    ],
    output: [
      ["answer", "string", "搜索后的回答内容，具体字段以返回结果为准。"],
      ["sources", "array", "可选，搜索引用来源。"],
      ["_account_email", "string", "本次使用的账号邮箱。"],
    ],
    example: (baseUrl: string, key: string) => `curl ${baseUrl}/search \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer ${key}" \\
  -d '{"prompt":"搜索 chatgpt2api 最新使用方式"}'`,
  },
  {
    title: "图片生成",
    method: "POST",
    path: "/v1/images/generations",
    icon: FileArchive,
    input: [
      ["prompt", "string", "图片生成提示词。"],
      ["model", "string", "可选，默认 gpt-image-2。"],
      ["n", "number", "可选，生成数量，当前限制 1-4。"],
      ["size", "string", "可选，图片尺寸。"],
      ["quality", "string", "可选，默认 auto。"],
      ["response_format", "string", "可选，默认 b64_json。"],
    ],
    output: [
      ["data", "array", "图片结果列表。"],
      ["data[].b64_json", "string", "base64 图片内容。"],
      ["data[].url", "string", "部分配置下返回图片 URL。"],
    ],
    example: (baseUrl: string, key: string) => `curl ${baseUrl}/images/generations \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer ${key}" \\
  -d '{"model":"gpt-image-2","prompt":"一张极简产品海报","n":1}'`,
  },
  {
    title: "图片编辑",
    method: "POST",
    path: "/v1/images/edits",
    icon: FileArchive,
    input: [
      ["image", "file | file[] | URL", "参考图，支持 multipart 上传，也支持 JSON 图片链接。"],
      ["prompt", "string", "编辑提示词。"],
      ["model", "string", "可选，默认 gpt-image-2。"],
      ["n", "number", "可选，生成数量，当前限制 1-4。"],
      ["size", "string", "可选，图片尺寸。"],
      ["quality", "string", "可选，默认 auto。"],
    ],
    output: [
      ["data", "array", "编辑后的图片结果列表。"],
      ["data[].b64_json", "string", "base64 图片内容。"],
      ["data[].url", "string", "部分配置下返回图片 URL。"],
    ],
    example: (baseUrl: string, key: string) => `curl ${baseUrl}/images/edits \\
  -H "Authorization: Bearer ${key}" \\
  -F "model=gpt-image-2" \\
  -F "prompt=改成赛博朋克夜景" \\
  -F "image=@./input.png"`,
  },
  {
    title: "创建 PPT 任务",
    method: "POST",
    path: "/v1/ppt/generations",
    icon: FileText,
    input: [
      ["prompt", "string", "PPT 需求描述，可为空但建议填写完整主题、页数、风格和内容结构。"],
      ["base64_images", "string[]", "可选，图片 data URL/base64，用作 PPT 参考素材。"],
      ["client_task_id", "string", "可选，客户端幂等任务 ID；重复提交同 ID 会返回已有任务。"],
    ],
    output: [
      ["id / taskId", "string", "任务 ID，用于轮询状态。"],
      ["status", "queued | running | success | error", "任务状态。"],
      ["kind", "ppt", "任务类型。"],
      ["created_at / updated_at", "string", "任务创建和更新时间。"],
    ],
    example: (baseUrl: string, key: string) => `curl ${baseUrl}/ppt/generations \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer ${key}" \\
  -d '{"prompt":"制作一份 8 页以内的季度业务汇报 PPT","base64_images":[]}'`,
  },
  {
    title: "创建 PSD 任务",
    method: "POST",
    path: "/v1/psd/generations",
    icon: FileArchive,
    input: [
      ["prompt", "string", "PSD 拆分与合成要求，例如保留图层、位置、背景和素材 zip。"],
      ["base64_images", "string[]", "必填，至少一张图片 data URL/base64，作为 PSD 拆分源图。"],
      ["client_task_id", "string", "可选，客户端幂等任务 ID。"],
    ],
    output: [
      ["id / taskId", "string", "任务 ID，用于轮询状态。"],
      ["status", "queued | running | success | error", "任务状态。"],
      ["kind", "psd", "任务类型。"],
      ["error", "string", "失败时返回错误信息。"],
    ],
    example: (baseUrl: string, key: string) => `curl ${baseUrl}/psd/generations \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer ${key}" \\
  -d '{"prompt":"按原图位置拆分海报元素并合成可编辑 PSD","base64_images":["data:image/png;base64,..."]}'`,
  },
  {
    title: "任务状态查询",
    method: "GET",
    path: "/v1/editable-file-tasks?ids={taskId1,taskId2}",
    icon: ListChecks,
    input: [
      ["ids", "string", "可选，逗号分隔任务 ID；不传则返回当前用户全部可编辑文件任务。"],
    ],
    output: [
      ["items", "array", "任务列表。成功任务的 result 内包含 primary_url 和 zip_url。"],
      ["missing_ids", "string[]", "查询指定 ids 时，返回未找到的任务 ID。"],
      ["result.primary_url", "string", "主文件下载地址。"],
      ["result.zip_url", "string", "素材 zip 下载地址。"],
    ],
    example: (baseUrl: string, key: string) => `curl "${baseUrl}/editable-file-tasks?ids=<task_id>" \\
  -H "Authorization: Bearer ${key}"`,
  },
  {
    title: "结果文件下载",
    method: "GET",
    path: "/files/{file_path}",
    icon: FileArchive,
    input: [
      ["file_path", "string", "由任务 result.primary_url 或 result.zip_url 返回，通常不需要手动拼接。"],
    ],
    output: [
      ["binary", "file", "返回 pptx/psd/zip 文件流。"],
    ],
    example: (baseUrl: string, _key: string) => `curl ${baseUrl.replace(/\/v1$/, "")}/files/<file_path> -o result.zip`,
  },
  {
    title: "修改代理配置",
    method: "POST",
    path: "/api/proxy/settings",
    icon: KeyRound,
    input: [
      ["Authorization", "header", "Bearer <admin-auth-key>，需管理员密钥。"],
      ["proxy_enabled", "boolean | -1", "可选，是否启用全局代理；传 -1 表示关闭。"],
      ["proxy_url", "string | -1", "可选，全局代理地址；传 -1 表示清空。"],
      ["account_proxy_list_enabled", "boolean | -1", "可选，是否启用账号代理列表；传 -1 表示关闭。"],
      ["account_proxy_list", "string[] | string | -1", "可选，账号代理列表（数组或换行分隔字符串）；传 -1 表示清空。"],
    ],
    output: [
      ["proxy", "object", "当前全局代理配置，含 enabled / url / interval_secs / rounds。"],
      ["account_proxy_list_enabled", "boolean", "账号代理列表是否启用。"],
      ["account_proxy_list", "string[]", "当前账号代理列表。"],
      ["accounts_per_proxy", "number", "每个代理连续分配的账号数量。"],
    ],
    example: (baseUrl: string, key: string) => `curl ${baseUrl.replace(/\/v1$/, "")}/api/proxy/settings \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer ${key}" \\
  -d '{"proxy_enabled":true,"proxy_url":"http://127.0.0.1:7890","account_proxy_list_enabled":true,"account_proxy_list":["http://a:8080","http://b:8080"]}'`,
  },
  {
    title: "Access Token 导入",
    method: "POST",
    path: "/api/accounts/import/access-token",
    icon: KeyRound,
    input: [
      ["Authorization", "header", "Bearer <admin-auth-key>，需管理员密钥。"],
      ["access_token", "string", "可选，单个 Access Token。"],
      ["tokens", "string[]", "可选，批量 Access Token 列表；可与 access_token 同时传。"],
      ["proxy", "string", "可选，账号代理；非空时保存到本次导入的每个账号并用于后续刷新。"],
    ],
    output: [
      ["added", "number", "新增账号数量。"],
      ["skipped", "number", "已存在而跳过的数量。"],
      ["refreshed", "number", "导入后成功刷新的账号数量。"],
      ["errors", "array", "刷新失败项及错误信息。"],
      ["items", "array", "当前账号列表。"],
    ],
    example: (baseUrl: string, key: string) => `curl ${baseUrl.replace(/\/v1$/, "")}/api/accounts/import/access-token \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer ${key}" \\
  -d '{"access_token":"<your-access-token>","proxy":"http://127.0.0.1:7890"}'`,
  },
  {
    title: "Session JSON 导入",
    method: "POST",
    path: "/api/accounts/import/session-json",
    icon: FileJson,
    input: [
      ["Authorization", "header", "Bearer <admin-auth-key>，需管理员密钥。"],
      ["session", "object", "可选，从 chatgpt.com/api/auth/session 复制的完整 JSON 对象。"],
      ["session_json", "string", "可选，Session JSON 原始字符串；与 session 二选一。"],
    ],
    output: [
      ["added", "number", "新增账号数量。"],
      ["skipped", "number", "已存在而跳过的数量。"],
      ["refreshed", "number", "导入后成功刷新的账号数量。"],
      ["errors", "array", "刷新失败项及错误信息。"],
      ["items", "array", "当前账号列表。"],
    ],
    example: (baseUrl: string, key: string) => `curl ${baseUrl.replace(/\/v1$/, "")}/api/accounts/import/session-json \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer ${key}" \\
  -d '{"session":{"accessToken":"<your-access-token>"}}'`,
  },
  {
    title: "正常账号统计",
    method: "GET",
    path: "/api/accounts/stats/normal",
    icon: ListChecks,
    input: [
      ["Authorization", "header", "Bearer <admin-auth-key>，需管理员密钥。"],
    ],
    output: [
      ["active_count", "number", "当前状态为「正常」的账号数量。"],
      ["total_quota", "number", "所有正常账号的剩余图片额度总和。"],
      ["invalid_account_recent_success_total", "number", "最近 10 个失效账号的出图合计。"],
    ],
    example: (baseUrl: string, key: string) => `curl ${baseUrl.replace(/\/v1$/, "")}/api/accounts/stats/normal \\
  -H "Authorization: Bearer ${key}"`,
  },
];

const usableModels = ["gpt-image-2", "codex-gpt-image-2", "auto", "gpt-5", "gpt-5-1", "gpt-5-2", "gpt-5-3", "gpt-5-3-mini", "gpt-5-mini"];

function ParamTable({ rows }: { rows: ParamRow[] }) {
  return (
    <div className="overflow-hidden rounded-lg border border-stone-200">
      <table className="w-full text-left text-xs">
        <thead className="bg-stone-50 text-stone-500">
          <tr>
            <th className="px-3 py-2 font-medium">参数</th>
            <th className="px-3 py-2 font-medium">类型</th>
            <th className="px-3 py-2 font-medium">说明</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-stone-100 bg-white">
          {rows.map(([name, type, desc]) => (
            <tr key={name}>
              <td className="px-3 py-2 font-mono text-stone-800">{name}</td>
              <td className="px-3 py-2 font-mono text-stone-500">{type}</td>
              <td className="px-3 py-2 text-stone-600">{desc}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ApiDocsCard() {
  const [authKey, setAuthKey] = useState("");
  const serviceBaseUrl = webConfig.apiUrl.replace(/\/$/, "") || (typeof window !== "undefined" ? window.location.origin : "");
  const openAIBaseUrl = `${serviceBaseUrl}/v1`;
  const displayKey = authKey || "<当前密钥>";

  useEffect(() => {
    let active = true;
    void getStoredAuthSession().then((session) => {
      if (active) setAuthKey(session?.key || "");
    });
    return () => {
      active = false;
    };
  }, []);

  return (
    <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
      <CardContent className="space-y-5 p-6">
        <div>
          <div className="flex items-center gap-2 text-base font-semibold text-stone-900">
            <KeyRound className="size-5 text-stone-500" />
            接口接入说明
          </div>
          <p className="mt-1 text-xs leading-6 text-stone-500">
            第三方应用按 OpenAI 兼容接口接入；文件任务、账号导入与代理配置接口也使用同一套 Bearer 鉴权，账号导入与代理配置需管理员密钥。
          </p>
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <div className="space-y-1 rounded-xl border border-stone-200 bg-white px-3 py-2">
            <div className="text-xs text-stone-500">服务地址</div>
            <div className="break-all font-mono text-xs text-stone-800">{serviceBaseUrl}</div>
          </div>
          <div className="space-y-1 rounded-xl border border-stone-200 bg-white px-3 py-2">
            <div className="text-xs text-stone-500">Base URL（OpenAI）</div>
            <div className="break-all font-mono text-xs text-stone-800">{openAIBaseUrl}</div>
          </div>
          <div className="space-y-1 rounded-xl border border-stone-200 bg-white px-3 py-2">
            <div className="text-xs text-stone-500">API Key</div>
            <div className="break-all font-mono text-xs text-stone-800">{displayKey}</div>
          </div>
          <div className="space-y-1 rounded-xl border border-stone-200 bg-white px-3 py-2">
            <div className="text-xs text-stone-500">请求头</div>
            <div className="break-all font-mono text-xs text-stone-800">Authorization: Bearer {displayKey}</div>
          </div>
        </div>

        <div className="space-y-2">
          <div className="text-xs font-medium text-stone-600">常用模型，也可请求 /v1/models 获取</div>
          <div className="flex flex-wrap gap-2">
            {usableModels.map((model) => (
              <span key={model} className="rounded-md border border-stone-200 bg-white px-2 py-1 font-mono text-xs text-stone-700">{model}</span>
            ))}
          </div>
        </div>

        <div className="space-y-3">
          {docs.map((item) => {
            const Icon = item.icon;
            return (
              <details key={item.path} className="group rounded-xl border border-stone-200 bg-white px-4 py-3">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-3">
                  <span className="flex min-w-0 items-center gap-3">
                    <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-stone-100 text-stone-600">
                      <Icon className="size-4" />
                    </span>
                    <span className="min-w-0">
                      <span className="block text-sm font-semibold text-stone-900">{item.title}</span>
                      <span className="mt-1 block truncate font-mono text-xs text-stone-500">{item.method} {item.path}</span>
                    </span>
                  </span>
                  <ChevronDown className="size-4 shrink-0 text-stone-400 transition group-open:rotate-180" />
                </summary>

                <div className="mt-4 grid gap-4 lg:grid-cols-2">
                  <div className="space-y-2">
                    <h3 className="text-xs font-semibold text-stone-700">输入参数</h3>
                    <ParamTable rows={item.input} />
                  </div>
                  <div className="space-y-2">
                    <h3 className="text-xs font-semibold text-stone-700">输出参数</h3>
                    <ParamTable rows={item.output} />
                  </div>
                  <div className="space-y-2 lg:col-span-2">
                    <h3 className="text-xs font-semibold text-stone-700">调用示例</h3>
                    <pre className="overflow-auto whitespace-pre-wrap break-all rounded-xl bg-stone-950 px-3 py-3 text-xs leading-5 text-stone-100">{item.example(openAIBaseUrl, displayKey)}</pre>
                  </div>
                </div>
              </details>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
