"use client";

import { useState } from "react";
import { Link2, LoaderCircle, PlugZap, Save } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { testProxy, type ProxyTestResult } from "@/lib/api";

import { useSettingsStore } from "../store";

export function ProxySettingsCard() {
  const [isTesting, setIsTesting] = useState(false);
  const [testResult, setTestResult] = useState<ProxyTestResult | null>(null);
  const config = useSettingsStore((state) => state.config);
  const isLoadingConfig = useSettingsStore((state) => state.isLoadingConfig);
  const isSavingConfig = useSettingsStore((state) => state.isSavingConfig);
  const setProxy = useSettingsStore((state) => state.setProxy);
  const setProxyField = useSettingsStore((state) => state.setProxyField);
  const saveConfig = useSettingsStore((state) => state.saveConfig);

  const proxy = (config?.proxy?.urls || []).join("\n");
  const proxyIntervalSecs = config?.proxy?.interval_secs ?? 2;
  const proxyRounds = config?.proxy?.rounds ?? 3;

  const handleTest = async () => {
    const urls = proxy
      .split(/\r?\n/)
      .map((item) => item.trim())
      .filter(Boolean);
    if (!urls.length) {
      toast.error("请先填写代理地址");
      return;
    }
    setIsTesting(true);
    setTestResult(null);
    try {
      const data = await testProxy("", urls);
      setTestResult(data.result);
      if (data.result.ok) {
        toast.success(`全部代理可用（${urls.length} 个）`);
      } else {
        toast.error(data.result.error ?? "部分代理不可用");
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "测试代理失败");
    } finally {
      setIsTesting(false);
    }
  };

  return (
    <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
      <CardContent className="space-y-6 p-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-xl bg-stone-100">
              <Link2 className="size-5 text-stone-600" />
            </div>
            <div>
              <h2 className="text-lg font-semibold tracking-tight">全局代理</h2>
              <p className="text-sm text-stone-500">
                GPT 上游在无账号代理时从列表随机选一个；`http://no_proxy` 表示直连。图片下载/上传仍走直连。保存后立即生效。
              </p>
            </div>
          </div>
          <Badge variant={proxy.trim() ? "success" : "secondary"} className="w-fit rounded-md px-2.5 py-1">
            {proxy.trim() ? "已配置" : "未配置"}
          </Badge>
        </div>

        {isLoadingConfig ? (
          <div className="flex items-center justify-center py-10">
            <LoaderCircle className="size-5 animate-spin text-stone-400" />
          </div>
        ) : (
          <>
            <div className="space-y-2">
              <label className="text-sm font-medium text-stone-700">代理地址</label>
              <Textarea
                value={proxy}
                onChange={(event) => {
                  setProxy(event.target.value);
                  setTestResult(null);
                }}
                placeholder={"http://user:pass@127.0.0.1:7890\nhttp://no_proxy"}
                className="min-h-24 rounded-xl border-stone-200 bg-white font-mono text-xs"
              />
              <p className="text-sm text-stone-500">
                一行一个。支持 http / https / socks5。socks5 会自动转为 socks5h。`http://no_proxy` 表示不走代理。
              </p>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <label className="text-sm font-medium text-stone-700">超时重连间隔（秒）</label>
                <Input
                  value={String(proxyIntervalSecs)}
                  onChange={(event) => setProxyField("interval_secs", event.target.value)}
                  placeholder="2"
                  className="h-11 rounded-xl border-stone-200 bg-white"
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-stone-700">重连轮数</label>
                <Input
                  value={String(proxyRounds)}
                  onChange={(event) => setProxyField("rounds", event.target.value)}
                  placeholder="3"
                  className="h-11 rounded-xl border-stone-200 bg-white"
                />
              </div>
            </div>
            <p className="text-sm text-stone-500">
              代理超时或连接失败时，按间隔重连，最多尝试配置的轮数。写入 `config.json` 的 `proxy.interval_secs` / `proxy.rounds`。
            </p>

            {testResult ? (
              <div
                className={`space-y-1 rounded-xl border px-4 py-3 text-sm leading-6 ${
                  testResult.ok
                    ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                    : "border-rose-200 bg-rose-50 text-rose-800"
                }`}
              >
                {(testResult.results && testResult.results.length > 0
                  ? testResult.results
                  : [{ url: "", ok: testResult.ok, status: testResult.status, latency_ms: testResult.latency_ms, error: testResult.error }]
                ).map((item, index) => (
                  <div key={`${item.url}-${index}`}>
                    {item.skipped
                      ? `${item.url || "http://no_proxy"}：直连（跳过探测）`
                      : item.ok
                        ? `${item.url || "代理"}：可用，HTTP ${item.status}，${item.latency_ms} ms`
                        : `${item.url || "代理"}：不可用，${item.error ?? "未知错误"}`}
                  </div>
                ))}
              </div>
            ) : null}

            <div className="flex justify-end gap-2">
              <Button
                variant="outline"
                className="h-10 rounded-xl border-stone-200 bg-white px-5 text-stone-700"
                onClick={() => void handleTest()}
                disabled={isTesting || isLoadingConfig}
              >
                {isTesting ? <LoaderCircle className="size-4 animate-spin" /> : <PlugZap className="size-4" />}
                测试代理
              </Button>
              <Button
                className="h-10 rounded-xl bg-stone-950 px-5 text-white hover:bg-stone-800"
                onClick={() => void saveConfig()}
                disabled={isSavingConfig}
              >
                {isSavingConfig ? <LoaderCircle className="size-4 animate-spin" /> : <Save className="size-4" />}
                保存配置
              </Button>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
