"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import styles from "./page.module.css";

type AgentConfig = {
  llm_mode: string;
  model: string;
  browser_mode?: string;
  filesystem_mode?: string;
  admin_auth_required?: boolean;
  max_steps_per_run: number;
};

type RuntimeStep = {
  step_id: string;
  index: number;
  type: string;
  status: "pending" | "running" | "waiting_for_input" | "completed" | "failed" | "cancelled";
  message?: string | null;
  error?: string | null;
  user_input_kind?: string | null;
  user_input_prompt?: string | null;
  requested_selector_target?: string | null;
  provided_selector?: string | null;
};

type RunState = {
  run_id: string;
  run_name: string;
  status: "pending" | "running" | "waiting_for_input" | "completed" | "failed" | "cancelled";
  prompt?: string | null;
  execution_mode?: "plan" | "autonomous";
  summary?: string | null;
  report_artifact?: string | null;
  steps: RuntimeStep[];
};

type TestCaseState = {
  test_case_id: string;
  name: string;
  description?: string;
  prompt?: string;
  start_url?: string | null;
  steps: Record<string, unknown>[];
  test_data?: JsonObject;
  selector_profile?: Record<string, string[]>;
  created_at: string;
  updated_at: string;
};

type TestCaseSummary = {
  test_case_id: string;
  name: string;
  description?: string;
  prompt?: string;
  start_url?: string | null;
  step_count: number;
  created_at: string;
  updated_at: string;
};

type PlanGenerateResponse = {
  run_name: string;
  start_url?: string | null;
  steps: Record<string, unknown>[];
};

type StepImportResponse = {
  run_name: string;
  start_url?: string | null;
  steps: Record<string, unknown>[];
  source_filename: string;
  imported_count: number;
};

type JsonObject = Record<string, unknown>;

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8080";
const ADMIN_API_TOKEN = process.env.NEXT_PUBLIC_ADMIN_API_TOKEN?.trim() ?? "";
const DEFAULT_MAX_STEPS = 300;
const SHOW_ADVANCED_INPUTS =
  process.env.NEXT_PUBLIC_SHOW_ADVANCED_INPUTS?.trim().toLowerCase() === "true";

function buildApiHeaders(options?: { json?: boolean }): HeadersInit {
  const headers: Record<string, string> = {};
  if (options?.json) headers["Content-Type"] = "application/json";
  if (ADMIN_API_TOKEN) headers["X-Admin-Token"] = ADMIN_API_TOKEN;
  return headers;
}

async function parseError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string };
    if (body.detail) return body.detail;
  } catch {
    // Ignore parse failures and use fallback message.
  }
  return `${response.status} ${response.statusText}`;
}

function toUserMessage(rawMessage: string): string {
  const lower = rawMessage.toLowerCase();
  if (
    lower.includes("invalid plan returned by brain") ||
    lower.includes("could not generate runnable steps") ||
    lower.includes("steps list should have at least 1 item")
  ) {
    return "Could not build runnable steps from that prompt. Add URL + clearer targets and try again.";
  }
  return rawMessage;
}

function isTerminal(status: RunState["status"] | undefined): boolean {
  return status === "completed" || status === "failed" || status === "cancelled";
}

function statusClass(status: RunState["status"] | RuntimeStep["status"] | undefined): string {
  if (status === "completed") return styles.statusCompleted;
  if (status === "failed") return styles.statusFailed;
  if (status === "running") return styles.statusRunning;
  if (status === "waiting_for_input") return styles.statusWaiting;
  if (status === "cancelled") return styles.statusCancelled;
  return styles.statusPending;
}

function formatStepType(stepType: string): string {
  return stepType
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatPlanValue(value: unknown): string {
  if (value === null || value === undefined) return "null";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function formatPlanStep(step: Record<string, unknown>): string {
  const rawType = typeof step.type === "string" ? step.type : "step";
  const typeLabel = formatStepType(rawType);
  const details = Object.entries(step)
    .filter(([key]) => key !== "type")
    .map(([key, value]) => `${key}=${formatPlanValue(value)}`)
    .join(", ");
  return details ? `${typeLabel}: ${details}` : typeLabel;
}

function buildPromptFallbackFromSteps(steps: Record<string, unknown>[]): string {
  if (!steps.length) return "";
  return steps
    .map((step, index) => `${index + 1}. ${formatPlanStep(step)}`)
    .join("\n");
}

function extractFirstUrl(text: string): string | null {
  const match = text.match(/https?:\/\/[^\s]+/i);
  return match ? match[0] : null;
}

function parseJsonObject(raw: string, label: string): JsonObject {
  const text = raw
    .replace(/\u2018|\u2019|\u2032/g, "'")
    .replace(/\u201c|\u201d|\u2033/g, '"')
    .trim();
  if (!text) return {};

  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new Error(`${label} must be valid JSON.`);
  }

  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error(`${label} must be a JSON object.`);
  }
  return parsed as JsonObject;
}

function buildPlanSignature(prompt: string, testDataInput: string, selectorProfileInput: string): string {
  return [
    prompt.trim(),
    testDataInput.trim(),
    selectorProfileInput.trim(),
  ].join("||");
}

function stepSupportsManualSelectorHelp(step: RuntimeStep): boolean {
  if (step.user_input_kind === "selector" && step.status === "waiting_for_input") {
    return true;
  }
  if (step.status !== "failed") {
    return false;
  }
  if (!["click", "type", "select", "wait", "handle_popup", "verify_text"].includes(step.type)) {
    return false;
  }
  const message = `${step.error ?? ""} ${step.message ?? ""}`.toLowerCase();
  if (!message.trim()) {
    return false;
  }
  const recoverableMarkers = [
    "timeout",
    "waiting for",
    "locator.",
    "element",
    "not found",
    "not visible",
    "strict mode violation",
    "would receive the click",
    "unexpected token",
    "parsing css selector",
    "all selector candidates failed",
    "no valid selector candidates",
    "no selector candidates available",
    "click failed for",
    "locator.click",
    "not attached",
    "intercept",
    "another element would receive the click",
    "resolved to 0 elements",
    "blocked=",
    "in_iframe=",
  ];
  return recoverableMarkers.some((marker) => message.includes(marker));
}

export default function Home() {
  const [config, setConfig] = useState<AgentConfig | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);

  const [prompt, setPrompt] = useState(
    "Open https://example.com, wait for full load, then verify h1 contains 'Example Domain'.",
  );
  const [testDataInput, setTestDataInput] = useState("{}");
  const [selectorProfileInput, setSelectorProfileInput] = useState("{}");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isSavingTestCase, setIsSavingTestCase] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [isRefreshingCases, setIsRefreshingCases] = useState(false);
  const [runningCaseId, setRunningCaseId] = useState<string | null>(null);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [requestInfo, setRequestInfo] = useState<string | null>(null);
  const [selectorHelpInput, setSelectorHelpInput] = useState("");
  const [isSubmittingSelectorHelp, setIsSubmittingSelectorHelp] = useState(false);
  const [planPreview, setPlanPreview] = useState<PlanGenerateResponse | null>(null);
  const [importedPlan, setImportedPlan] = useState<StepImportResponse | null>(null);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [planSignature, setPlanSignature] = useState("");
  const [testCaseName, setTestCaseName] = useState("");
  const [testCaseDescription, setTestCaseDescription] = useState("");
  const [savedCases, setSavedCases] = useState<TestCaseSummary[]>([]);

  const [currentRun, setCurrentRun] = useState<RunState | null>(null);

  const runIsActive = useMemo(
    () => currentRun && !isTerminal(currentRun.status),
    [currentRun],
  );
  const reportUrl = useMemo(() => {
    if (!currentRun?.run_id || !currentRun?.report_artifact) return null;
    return `${API_BASE_URL}/api/runs/${currentRun.run_id}/artifacts/report.html`;
  }, [currentRun]);
  const planIsFresh = useMemo(() => {
    if (!planPreview) return false;
    const currentSignature = buildPlanSignature(prompt, testDataInput, selectorProfileInput);
    return planSignature === currentSignature;
  }, [planPreview, planSignature, prompt, selectorProfileInput, testDataInput]);
  const visiblePlan = useMemo<PlanGenerateResponse | null>(() => {
    if (importedPlan) {
      return {
        run_name: importedPlan.run_name,
        start_url: importedPlan.start_url ?? null,
        steps: importedPlan.steps,
      };
    }
    return SHOW_ADVANCED_INPUTS ? planPreview : null;
  }, [importedPlan, planPreview]);
  const waitingStep = useMemo(
    () =>
      currentRun?.steps.find(
        (step) => step.status === "waiting_for_input" && step.user_input_kind === "selector",
      ) ?? null,
    [currentRun],
  );
  const manualSelectorStep = useMemo(
    () => currentRun?.steps.find((step) => stepSupportsManualSelectorHelp(step)) ?? null,
    [currentRun],
  );

  useEffect(() => {
    let disposed = false;

    async function loadConfig(): Promise<void> {
      try {
        const response = await fetch(`${API_BASE_URL}/api/config`, {
          cache: "no-store",
          headers: buildApiHeaders(),
        });
        if (!response.ok) {
          throw new Error(await parseError(response));
        }
        const payload = (await response.json()) as AgentConfig;
        if (!disposed) {
          setConfig(payload);
          setConfigError(null);
        }
      } catch (error) {
        if (!disposed) {
          setConfigError(error instanceof Error ? error.message : "Failed to load config");
        }
      }
    }

    void loadConfig();
    return () => {
      disposed = true;
    };
  }, []);

  const loadTestCases = useCallback(async (options?: { silent?: boolean }): Promise<void> => {
    const silent = options?.silent ?? false;
    if (!silent) {
      setIsRefreshingCases(true);
    }
    try {
      const response = await fetch(`${API_BASE_URL}/api/test-cases`, {
        cache: "no-store",
        headers: buildApiHeaders(),
      });
      if (!response.ok) {
        throw new Error(await parseError(response));
      }
      const payload = (await response.json()) as { items: TestCaseSummary[] };
      setSavedCases(payload.items ?? []);
    } catch (error) {
      setRequestError(error instanceof Error ? error.message : "Failed to load test cases");
    } finally {
      if (!silent) {
        setIsRefreshingCases(false);
      }
    }
  }, []);

  useEffect(() => {
    void loadTestCases({ silent: true });
  }, [loadTestCases]);

  useEffect(() => {
    if (!currentRun) return;
    const shouldPoll = !isTerminal(currentRun.status) || !currentRun.report_artifact;
    if (!shouldPoll) return;

    const interval = setInterval(async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/runs/${currentRun.run_id}`, {
          cache: "no-store",
          headers: buildApiHeaders(),
        });
        if (!response.ok) return;
        const payload = (await response.json()) as RunState;
        setCurrentRun(payload);
      } catch {
        // Poll errors are ignored while run is active.
      }
    }, 1200);

    return () => clearInterval(interval);
  }, [currentRun]);

  async function requestPlan(
    task: string,
    testData: JsonObject,
    selectorProfile: JsonObject,
  ): Promise<PlanGenerateResponse> {
    const planResponse = await fetch(`${API_BASE_URL}/api/plan`, {
      method: "POST",
      headers: buildApiHeaders({ json: true }),
      body: JSON.stringify({
        task,
        max_steps: config?.max_steps_per_run ?? DEFAULT_MAX_STEPS,
        test_data: testData,
        selector_profile: selectorProfile,
      }),
    });
    if (!planResponse.ok) {
      throw new Error(await parseError(planResponse));
    }

    const plan = (await planResponse.json()) as PlanGenerateResponse;
    if (!plan.steps || plan.steps.length === 0) {
      throw new Error("Planner returned no executable steps.");
    }
    return plan;
  }

  async function generatePlanPreview(): Promise<void> {
    setRequestError(null);
    setRequestInfo(null);

    const task = prompt.trim();
    if (!task) {
      setRequestError("Enter a prompt first.");
      return;
    }
    let testData: JsonObject;
    let selectorProfile: JsonObject;
    try {
      if (SHOW_ADVANCED_INPUTS) {
        testData = parseJsonObject(testDataInput, "Test Data");
        selectorProfile = parseJsonObject(selectorProfileInput, "Selector Profile");
      } else {
        testData = {};
        selectorProfile = {};
      }
    } catch (error) {
      setRequestError(error instanceof Error ? error.message : "Invalid JSON configuration");
      return;
    }

    try {
      setIsGenerating(true);
      setImportedPlan(null);
      const plan = await requestPlan(task, testData, selectorProfile);
      setPlanPreview(plan);
      setPlanSignature(buildPlanSignature(prompt, testDataInput, selectorProfileInput));
    } catch (error) {
      const rawMessage = error instanceof Error ? error.message : "Failed to generate plan";
      setRequestError(toUserMessage(rawMessage));
    } finally {
      setIsGenerating(false);
    }
  }

  async function importStepsFromFile(): Promise<void> {
    setRequestError(null);
    setRequestInfo(null);

    if (!importFile) {
      setRequestError("Choose a .csv or .xlsx file first.");
      return;
    }

    try {
      setIsImporting(true);
      const formData = new FormData();
      formData.append("file", importFile);
      const normalizedName = testCaseName.trim();
      if (normalizedName) {
        formData.append("run_name", normalizedName);
      }

      const response = await fetch(`${API_BASE_URL}/api/test-cases/import`, {
        method: "POST",
        headers: buildApiHeaders(),
        body: formData,
      });
      if (!response.ok) {
        throw new Error(await parseError(response));
      }

      const imported = (await response.json()) as StepImportResponse;
      setImportedPlan(imported);
      setPlanPreview({
        run_name: imported.run_name,
        start_url: imported.start_url ?? null,
        steps: imported.steps,
      });
      setPlanSignature("");
      if (!normalizedName) {
        setTestCaseName(imported.run_name);
      }
      setRequestInfo(
        `Imported ${imported.imported_count} steps from ${imported.source_filename}. Running now will use imported steps.`,
      );
    } catch (error) {
      const rawMessage = error instanceof Error ? error.message : "Failed to import steps file";
      setRequestError(toUserMessage(rawMessage));
    } finally {
      setIsImporting(false);
    }
  }

  function clearImportedPlan(): void {
    setImportedPlan(null);
    setRequestInfo("Imported steps cleared. Prompt planning mode is active.");
  }

  async function runFromPrompt(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setRequestError(null);
    setRequestInfo(null);

    const task = prompt.trim();
    if (!task && !importedPlan) {
      setRequestError("Enter a prompt first.");
      return;
    }
    let testData: JsonObject;
    let selectorProfile: JsonObject;
    try {
      if (SHOW_ADVANCED_INPUTS) {
        testData = parseJsonObject(testDataInput, "Test Data");
        selectorProfile = parseJsonObject(selectorProfileInput, "Selector Profile");
      } else {
        testData = {};
        selectorProfile = {};
      }
    } catch (error) {
      setRequestError(error instanceof Error ? error.message : "Invalid JSON configuration");
      return;
    }

    try {
      setIsSubmitting(true);
      const runPayload = importedPlan
        ? {
            run_name: importedPlan.run_name || "prompt-run",
            start_url: importedPlan.start_url ?? null,
            steps: importedPlan.steps,
            test_data: testData,
            selector_profile: selectorProfile,
          }
        : {
            run_name: "autonomous-browser-run",
            start_url: extractFirstUrl(task),
            prompt: task,
            execution_mode: "autonomous",
            steps: [],
            test_data: testData,
            selector_profile: selectorProfile,
          };

      const runResponse = await fetch(`${API_BASE_URL}/api/runs`, {
        method: "POST",
        headers: buildApiHeaders({ json: true }),
        body: JSON.stringify(runPayload),
      });
      if (!runResponse.ok) {
        throw new Error(await parseError(runResponse));
      }

      const run = (await runResponse.json()) as RunState;
      setCurrentRun(run);
      setRequestInfo(`Run started: ${run.run_id}`);
    } catch (error) {
      const rawMessage = error instanceof Error ? error.message : "Failed to execute prompt";
      setRequestError(toUserMessage(rawMessage));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function saveTestCaseFromPrompt(): Promise<void> {
    setRequestError(null);
    setRequestInfo(null);

    const task = prompt.trim();
    if (!task && !importedPlan) {
      setRequestError("Enter a prompt first.");
      return;
    }

    const normalizedName = testCaseName.trim();
    if (!normalizedName) {
      setRequestError("Enter test case name before saving.");
      return;
    }

    let testData: JsonObject;
    let selectorProfile: JsonObject;
    try {
      if (SHOW_ADVANCED_INPUTS) {
        testData = parseJsonObject(testDataInput, "Test Data");
        selectorProfile = parseJsonObject(selectorProfileInput, "Selector Profile");
      } else {
        testData = {};
        selectorProfile = {};
      }
    } catch (error) {
      setRequestError(error instanceof Error ? error.message : "Invalid JSON configuration");
      return;
    }

    try {
      setIsSavingTestCase(true);
      let plan: PlanGenerateResponse;
      if (importedPlan) {
        plan = {
          run_name: importedPlan.run_name,
          start_url: importedPlan.start_url ?? null,
          steps: importedPlan.steps,
        };
      } else {
        const useCachedPlan = SHOW_ADVANCED_INPUTS && Boolean(planIsFresh && planPreview);
        plan = useCachedPlan && planPreview ? planPreview : await requestPlan(task, testData, selectorProfile);
        if (!useCachedPlan) {
          setPlanPreview(plan);
          setPlanSignature(buildPlanSignature(prompt, testDataInput, selectorProfileInput));
        }
      }

      const response = await fetch(`${API_BASE_URL}/api/test-cases`, {
        method: "POST",
        headers: buildApiHeaders({ json: true }),
        body: JSON.stringify({
          name: normalizedName,
          description: testCaseDescription.trim(),
          prompt: task || buildPromptFallbackFromSteps(plan.steps),
          start_url: plan.start_url ?? null,
          steps: plan.steps,
          test_data: testData,
          selector_profile: selectorProfile,
        }),
      });
      if (!response.ok) {
        throw new Error(await parseError(response));
      }
      const saved = (await response.json()) as TestCaseState;
      setRequestInfo(`Saved test case: ${saved.name}`);
      await loadTestCases({ silent: true });
    } catch (error) {
      const rawMessage = error instanceof Error ? error.message : "Failed to save test case";
      setRequestError(toUserMessage(rawMessage));
    } finally {
      setIsSavingTestCase(false);
    }
  }

  async function runSavedTestCase(testCaseId: string): Promise<void> {
    setRequestError(null);
    setRequestInfo(null);
    try {
      setRunningCaseId(testCaseId);
      const detailResponse = await fetch(`${API_BASE_URL}/api/test-cases/${testCaseId}`, {
        cache: "no-store",
        headers: buildApiHeaders(),
      });
      if (detailResponse.ok) {
        const detail = (await detailResponse.json()) as TestCaseState;
        const savedPrompt = (detail.prompt ?? "").trim();
        const fallbackPrompt = buildPromptFallbackFromSteps(detail.steps ?? []);
        setPrompt(savedPrompt || fallbackPrompt);
        setTestCaseName(detail.name ?? "");
        setTestCaseDescription(detail.description ?? "");
      }

      const response = await fetch(`${API_BASE_URL}/api/test-cases/${testCaseId}/run`, {
        method: "POST",
        headers: buildApiHeaders(),
      });
      if (!response.ok) {
        throw new Error(await parseError(response));
      }
      const run = (await response.json()) as RunState;
      setCurrentRun(run);
      setRequestInfo(`Run started from saved test case: ${run.run_name}`);
    } catch (error) {
      setRequestError(error instanceof Error ? error.message : "Failed to run saved test case");
    } finally {
      setRunningCaseId(null);
    }
  }

  async function cancelRun(): Promise<void> {
    if (!currentRun || isTerminal(currentRun.status)) return;

    try {
      setIsCancelling(true);
      const response = await fetch(`${API_BASE_URL}/api/runs/${currentRun.run_id}/cancel`, {
        method: "POST",
        headers: buildApiHeaders(),
      });
      if (!response.ok) {
        throw new Error(await parseError(response));
      }

      const refreshed = await fetch(`${API_BASE_URL}/api/runs/${currentRun.run_id}`, {
        cache: "no-store",
        headers: buildApiHeaders(),
      });
      if (refreshed.ok) {
        const payload = (await refreshed.json()) as RunState;
        setCurrentRun(payload);
      }
    } catch (error) {
      setRequestError(error instanceof Error ? error.message : "Failed to cancel run");
    } finally {
      setIsCancelling(false);
    }
  }

  async function submitSelectorHelp(): Promise<void> {
    if (!currentRun || !manualSelectorStep) return;
    const selector = selectorHelpInput.trim();
    if (!selector) {
      setRequestError("Enter a selector before submitting help.");
      return;
    }

    try {
      setIsSubmittingSelectorHelp(true);
      setRequestError(null);
      setRequestInfo(null);

      const response = await fetch(
        `${API_BASE_URL}/api/runs/${currentRun.run_id}/steps/${manualSelectorStep.step_id}/selector`,
        {
          method: "POST",
          headers: buildApiHeaders({ json: true }),
          body: JSON.stringify({ selector }),
        },
      );
      if (!response.ok) {
        throw new Error(await parseError(response));
      }
      const payload = (await response.json()) as RunState;
      setCurrentRun(payload);
      setSelectorHelpInput("");
      setRequestInfo("Selector received. The run is resuming from the blocked step.");
    } catch (error) {
      setRequestError(error instanceof Error ? error.message : "Failed to submit selector help");
    } finally {
      setIsSubmittingSelectorHelp(false);
    }
  }

  return (
    <div className={styles.shell}>
      <header className={styles.hero}>
        <div className={styles.heroLeft}>
          <p className={styles.kicker}>Tekno Phantom</p>
          <h1>Tekno Phantom</h1>
          <p className={styles.subtitle}>
            Prompt in, result out. Describe your browser task in plain language and Tekno Phantom
            will plan and execute it automatically.
          </p>
        </div>
        <div className={styles.heroRight}>
          <div className={styles.heroCard}>
            <p className={styles.heroCardTitle}>Live Config</p>
            {configError ? (
              <p className={styles.errorText}>{configError}</p>
            ) : (
              <p className={styles.metaLine}>
                {config?.llm_mode ?? "loading"} · {config?.model ?? "loading"} ·{" "}
                {config?.browser_mode ?? "loading"} · {config?.filesystem_mode ?? "loading"}
              </p>
            )}
          </div>
          <div className={styles.heroCardMuted}>
            <p>Natural-language browser automation with save + rerun support.</p>
          </div>
        </div>
      </header>

      <main className={styles.workspace}>
        <div className={styles.primaryColumn}>
          <section className={styles.panel}>
            <h2>Automation Prompt</h2>
            <form onSubmit={runFromPrompt} className={styles.form}>
              <label className={styles.fieldLabel}>
                <span>Prompt</span>
                <textarea
                  rows={4}
                  value={prompt}
                  onChange={(event) => setPrompt(event.target.value)}
                  placeholder="Example: Open https://example.com and verify h1 contains Example Domain."
                />
              </label>

              <div className={styles.fieldSplit}>
                <label className={styles.fieldLabel}>
                  <span>Test Case Name</span>
                  <input
                    value={testCaseName}
                    onChange={(event) => setTestCaseName(event.target.value)}
                    placeholder="Create_Form_01"
                  />
                </label>

                <label className={styles.fieldLabel}>
                  <span>Description</span>
                  <textarea
                    rows={2}
                    value={testCaseDescription}
                    onChange={(event) => setTestCaseDescription(event.target.value)}
                    placeholder="Create form flow with required field verification."
                  />
                </label>
              </div>

              <div className={styles.importBlock}>
                <label className={styles.fieldLabel}>
                  <span>Import Steps File (.csv / .xlsx)</span>
                  <input
                    className={styles.fileInput}
                    type="file"
                    accept=".csv,.xlsx"
                    onChange={(event) => {
                      const selected = event.target.files?.[0] ?? null;
                      setImportFile(selected);
                    }}
                  />
                </label>
                <div className={styles.importActions}>
                  <button
                    type="button"
                    className={styles.secondaryButton}
                    onClick={importStepsFromFile}
                    disabled={!importFile || isImporting || isSubmitting || isSavingTestCase}
                  >
                    {isImporting ? "Importing..." : "Import Steps"}
                  </button>
                  {importedPlan ? (
                    <button
                      type="button"
                      className={styles.secondaryButton}
                      onClick={clearImportedPlan}
                      disabled={isSubmitting || isSavingTestCase}
                    >
                      Clear Imported
                    </button>
                  ) : null}
                </div>
              </div>

              {SHOW_ADVANCED_INPUTS ? (
                <>
                  <label className={styles.fieldLabel}>
                    <span>Test Data (JSON)</span>
                    <textarea
                      rows={5}
                      value={testDataInput}
                      onChange={(event) => setTestDataInput(event.target.value)}
                      placeholder='{"email":"qa@example.com","password":"secret123"}'
                    />
                  </label>

                  <label className={styles.fieldLabel}>
                    <span>Selector Profile (JSON)</span>
                    <textarea
                      rows={5}
                      value={selectorProfileInput}
                      onChange={(event) => setSelectorProfileInput(event.target.value)}
                      placeholder='{"email":["#username"],"password":["#password"]}'
                    />
                  </label>
                </>
              ) : null}

              {requestError ? <p className={styles.errorText}>{requestError}</p> : null}
              {requestInfo ? <p className={styles.infoText}>{requestInfo}</p> : null}

              <div className={styles.actions}>
                {SHOW_ADVANCED_INPUTS ? (
                  <button
                    type="button"
                    className={styles.secondaryButton}
                    onClick={generatePlanPreview}
                    disabled={isGenerating || isSubmitting}
                  >
                    {isGenerating ? "Generating..." : "Generate Steps (AI)"}
                  </button>
                ) : null}
                <button
                  type="button"
                  className={styles.secondaryButton}
                  onClick={saveTestCaseFromPrompt}
                  disabled={isSavingTestCase || isSubmitting || isImporting}
                >
                  {isSavingTestCase ? "Saving..." : "Save Test Case"}
                </button>
                <button type="submit" className={styles.primaryButton} disabled={isSubmitting || isImporting}>
                  {isSubmitting ? "Starting..." : "Run Prompt"}
                </button>
                <button
                  type="button"
                  className={styles.secondaryButton}
                  onClick={cancelRun}
                  disabled={!runIsActive || isCancelling}
                >
                  {isCancelling ? "Cancelling..." : "Cancel"}
                </button>
              </div>

              {visiblePlan ? (
                <div className={styles.planPreview}>
                  <div className={styles.planHeader}>
                    <h3>
                      {importedPlan ? "Imported Steps" : "Generated Steps"} ({visiblePlan.steps.length})
                    </h3>
                    {!importedPlan && SHOW_ADVANCED_INPUTS && !planIsFresh ? (
                      <p className={styles.planStale}>Prompt changed. Generate steps again before run.</p>
                    ) : null}
                  </div>
                  {importedPlan ? (
                    <p className={styles.metaLine}>Source: {importedPlan.source_filename}</p>
                  ) : null}
                  <p className={styles.metaLine}>
                    Run Name: {visiblePlan.run_name}
                    {visiblePlan.start_url ? ` | Start URL: ${visiblePlan.start_url}` : ""}
                  </p>
                  <ol className={styles.planList}>
                    {visiblePlan.steps.map((step, index) => (
                      <li key={`plan-step-${index}`} className={styles.planItem}>
                        {formatPlanStep(step)}
                      </li>
                    ))}
                  </ol>
                </div>
              ) : null}
            </form>
          </section>

          <section className={styles.panel}>
            <div className={styles.savedHeader}>
              <h2>Saved Test Cases</h2>
              <button
                type="button"
                className={styles.secondaryButton}
                onClick={() => void loadTestCases()}
                disabled={isRefreshingCases}
              >
                {isRefreshingCases ? "Refreshing..." : "Refresh"}
              </button>
            </div>

            {savedCases.length === 0 ? (
              <p className={styles.emptyState}>No saved test cases yet.</p>
            ) : (
              <div className={styles.savedList}>
                {savedCases.map((testCase) => (
                  <article key={testCase.test_case_id} className={styles.savedItem}>
                    <div className={styles.savedItemTop}>
                      <div>
                        <p className={styles.savedName}>{testCase.name}</p>
                        {testCase.description ? <p className={styles.savedDesc}>{testCase.description}</p> : null}
                        <p className={styles.metaLine}>
                          Steps: {testCase.step_count}
                          {testCase.start_url ? ` · Start URL: ${testCase.start_url}` : ""}
                        </p>
                      </div>
                      <button
                        type="button"
                        className={styles.primaryButton}
                        onClick={() => void runSavedTestCase(testCase.test_case_id)}
                        disabled={Boolean(runningCaseId)}
                      >
                        {runningCaseId === testCase.test_case_id ? "Starting..." : "Run"}
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>
        </div>

        <section className={`${styles.panel} ${styles.resultPanel}`}>
          <h2>Result</h2>
          {!currentRun ? (
            <p className={styles.emptyState}>No result yet. Submit a prompt to run automation.</p>
          ) : (
            <>
              <div className={styles.runHeader}>
                <div>
                  <p className={styles.runName}>{currentRun.run_name}</p>
                  <p className={styles.metaLine}>Run ID: {currentRun.run_id}</p>
                </div>
                <div className={styles.runHeaderActions}>
                  {reportUrl ? (
                    <a
                      className={styles.secondaryButton}
                      href={reportUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      View Report
                    </a>
                  ) : null}
                  <p className={`${styles.statusPill} ${statusClass(currentRun.status)}`}>
                    {currentRun.status}
                  </p>
                </div>
              </div>

              {currentRun.summary ? <p className={styles.summary}>{currentRun.summary}</p> : null}

              {manualSelectorStep ? (
                <div className={styles.helpCard}>
                  <p className={styles.helpTitle}>Selector Help Needed</p>
                  <p className={styles.stepError}>{manualSelectorStep.error}</p>
                  <p className={styles.helpText}>
                    {manualSelectorStep.user_input_prompt ??
                      "Provide a Playwright selector for the element the agent could not find."}
                  </p>
                  <p className={styles.metaLine}>
                    Tips: SelectorHub output can still fail if it is XPath instead of Playwright CSS/text
                    syntax, if the element is inside an iframe, if the locator is dynamic, or if the page
                    changed after load. Prefer short Playwright selectors like `button:has-text('Workflows')`,
                    `a[href*='workflow']`, `#id`, `[data-testid='...']`, or `input[name='...']`.
                    Paste only the selector itself, not code like `await page.locator(...)`.
                  </p>
                  {manualSelectorStep.provided_selector ? (
                    <p className={styles.metaLine}>
                      Last selector tried: {manualSelectorStep.provided_selector}
                    </p>
                  ) : null}
                  {manualSelectorStep.requested_selector_target ? (
                    <p className={styles.metaLine}>
                      Needed for: {manualSelectorStep.requested_selector_target}
                    </p>
                  ) : null}
                  <label className={styles.fieldLabel}>
                    <span>Selector / Locator</span>
                    <input
                      value={selectorHelpInput}
                      onChange={(event) => setSelectorHelpInput(event.target.value)}
                      placeholder="Example: button:has-text('Workflows')"
                    />
                  </label>
                  <div className={styles.actions}>
                    <button
                      type="button"
                      className={styles.primaryButton}
                      onClick={submitSelectorHelp}
                      disabled={isSubmittingSelectorHelp}
                    >
                      {isSubmittingSelectorHelp ? "Submitting..." : "Submit Selector And Resume"}
                    </button>
                  </div>
                </div>
              ) : null}

              <div className={styles.timeline}>
                {currentRun.steps.map((step) => (
                  <article key={step.step_id} className={styles.timelineItem}>
                    <div className={styles.timelineTop}>
                      <p>
                        #{step.index + 1} {formatStepType(step.type)}
                      </p>
                      <p className={`${styles.statusPill} ${statusClass(step.status)}`}>
                        {step.status}
                      </p>
                    </div>
                    {step.message ? <p className={styles.stepMessage}>{step.message}</p> : null}
                    {step.error ? (
                      <p className={styles.stepError}>{step.error}</p>
                    ) : step.status === "failed" ? (
                      <p className={styles.stepError}>
                        Step failed with no details returned. Re-run once and check backend logs with Run ID:
                        {" "}
                        {currentRun.run_id}
                      </p>
                    ) : null}
                    {stepSupportsManualSelectorHelp(step) ? (
                      <div className={styles.inlineHelpCard}>
                        <p className={styles.helpTitle}>Selector Needed For This Step</p>
                        <p className={styles.helpText}>
                          {step.user_input_prompt ??
                            "Provide a Playwright selector for the element the agent could not find."}
                        </p>
                        {step.requested_selector_target ? (
                          <p className={styles.metaLine}>Needed for: {step.requested_selector_target}</p>
                        ) : null}
                        <label className={styles.fieldLabel}>
                          <span>Selector / Locator</span>
                          <input
                            value={selectorHelpInput}
                            onChange={(event) => setSelectorHelpInput(event.target.value)}
                            placeholder="Example: button:has-text('Continue')"
                          />
                        </label>
                        <div className={styles.actions}>
                          <button
                            type="button"
                            className={styles.primaryButton}
                            onClick={submitSelectorHelp}
                            disabled={isSubmittingSelectorHelp}
                          >
                            {isSubmittingSelectorHelp ? "Submitting..." : "Submit Selector And Resume"}
                          </button>
                        </div>
                      </div>
                    ) : null}
                  </article>
                ))}
              </div>
            </>
          )}
        </section>
      </main>
    </div>
  );
}

