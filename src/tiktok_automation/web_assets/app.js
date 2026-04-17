const form = document.getElementById("job-form");
const submitButton = document.getElementById("submit-button");
const statusPanel = document.getElementById("status-panel");
const statusText = document.getElementById("status-text");
const statusMessage = document.getElementById("status-message");
const statusMeta = document.getElementById("status-meta");
const resultsPanel = document.getElementById("results-panel");
const resultsTitle = document.getElementById("results-title");
const resultsSubtitle = document.getElementById("results-subtitle");
const resultsGrid = document.getElementById("results-grid");
const recentGrid = document.getElementById("recent-grid");
const resultTemplate = document.getElementById("result-card-template");
const recentTemplate = document.getElementById("recent-card-template");
const topKInput = document.getElementById("top-k");
const renderTopKInput = document.getElementById("render-top-k");

let activePoll = null;

function formatDuration(seconds) {
  if (seconds == null) {
    return "-";
  }
  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  const rem = total % 60;
  return `${minutes}:${String(rem).padStart(2, "0")}`;
}

function formatDateTime(value) {
  if (!value) {
    return "";
  }
  return new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function setStatus(job) {
  statusPanel.classList.remove("hidden");
  statusText.textContent = job.status;
  statusMessage.textContent = job.message || "";
  statusMeta.textContent = job.run_id
    ? `run_id: ${job.run_id} · etapa: ${job.stage}`
    : `etapa: ${job.stage}`;
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || "Falha na requisicao.");
  }
  return payload;
}

function syncRenderCount() {
  const topK = Number(topKInput.value || 1);
  const renderTopK = Number(renderTopKInput.value || topK);
  renderTopKInput.value = Math.max(topK, renderTopK);
}

function applyQueueState(candidate, queueBadge, queueNote, approveButton) {
  const queue = candidate.queue;
  const post = candidate.post;
  queueBadge.removeAttribute("data-state");
  queueNote.textContent = "";

  if (post) {
    queueBadge.dataset.state = "posted";
    queueBadge.textContent = post.publish_id === "manual" ? "Postado manual" : "Postado";
    queueNote.textContent = `Publicado em ${formatDateTime(post.posted_at)} · publish_id ${post.publish_id || "-"}`;
    approveButton.disabled = true;
    approveButton.textContent = "Postado";
    return;
  }

  if (!queue) {
    queueBadge.textContent = "Livre";
    approveButton.disabled = false;
    approveButton.textContent = "Aprovar";
    return;
  }

  if (queue.status === "queued") {
    queueBadge.dataset.state = "queued";
    queueBadge.textContent = "Na fila";
    queueNote.textContent = `Janela escolhida: ${formatDateTime(queue.scheduled_at)} · ${queue.schedule_reason || "slot automatico"} · email sai 5 min antes com video, caption e hashtags.`;
    approveButton.disabled = false;
    approveButton.textContent = "Atualizar fila";
    return;
  }

  if (queue.status === "notifying") {
    queueBadge.dataset.state = "queued";
    queueBadge.textContent = "Enviando";
    queueNote.textContent = "Preparando email com video, caption e hashtags.";
    approveButton.disabled = true;
    approveButton.textContent = "Enviando";
    return;
  }

  if (queue.status === "notified") {
    queueBadge.dataset.state = "queued";
    queueBadge.textContent = "Avisado";
    queueNote.textContent = `Email enviado em ${formatDateTime(queue.notification_sent_at)} · janela ${formatDateTime(queue.scheduled_at)}.`;
    approveButton.disabled = false;
    approveButton.textContent = "Marcar postado";
    return;
  }

  if (queue.status === "posting") {
    queueBadge.dataset.state = "queued";
    queueBadge.textContent = "Postando";
    queueNote.textContent = "Aprovado e aguardando confirmacao da plataforma.";
    approveButton.disabled = true;
    approveButton.textContent = "Postando";
    return;
  }

  if (queue.status === "failed") {
    queueBadge.dataset.state = "failed";
    queueBadge.textContent = "Falhou";
    queueNote.textContent = queue.error || "Falha ao postar. Pode aprovar de novo.";
    approveButton.disabled = false;
    approveButton.textContent = "Reenfileirar";
    return;
  }
}

function renderRun(summary) {
  resultsPanel.classList.remove("hidden");
  resultsTitle.textContent = `${summary.title} · ${summary.rendered_count} videos`;
  resultsSubtitle.textContent =
    summary.rendered_count === summary.candidate_count
      ? "Todos os candidatos ranqueados foram renderizados."
      : `${summary.rendered_count} de ${summary.candidate_count} candidatos estao renderizados neste run.`;
  resultsGrid.innerHTML = "";

  summary.candidates.forEach((candidate) => {
    const fragment = resultTemplate.content.cloneNode(true);
    const card = fragment.querySelector(".result-card");
    const video = fragment.querySelector("video");
    const rankBadge = fragment.querySelector(".rank-badge");
    const scoreBadge = fragment.querySelector(".score-badge");
    const queueBadge = fragment.querySelector(".queue-badge");
    const title = fragment.querySelector(".result-title");
    const meta = fragment.querySelector(".result-meta");
    const reasonList = fragment.querySelector(".reason-list");
    const captionInput = fragment.querySelector(".caption-input");
    const queueNote = fragment.querySelector(".queue-note");
    const copyButton = fragment.querySelector(".copy-button");
    const approveButton = fragment.querySelector(".approve-button");
    const fileLink = fragment.querySelector(".file-link");

    video.src = candidate.video_url;
    rankBadge.textContent = `#${candidate.rank}`;
    scoreBadge.textContent = `score ${candidate.score}`;
    title.textContent = candidate.title;
    meta.textContent = `${formatDuration(candidate.duration_seconds)} · ${summary.transcript_provider || "desconhecido"} · ${summary.transcript_language || "-"}`;
    captionInput.value = candidate.queue?.caption || candidate.post?.caption || candidate.suggested_caption;
    fileLink.href = candidate.video_url;

    reasonList.innerHTML = "";
    candidate.reasons.forEach((reason) => {
      const item = document.createElement("li");
      item.textContent = reason;
      reasonList.appendChild(item);
    });

    applyQueueState(candidate, queueBadge, queueNote, approveButton);

    copyButton.addEventListener("click", async () => {
      await navigator.clipboard.writeText(captionInput.value);
      copyButton.textContent = "Copiado";
      window.setTimeout(() => {
        copyButton.textContent = "Copiar caption";
      }, 1400);
    });

    approveButton.addEventListener("click", async () => {
      approveButton.disabled = true;
      approveButton.textContent = candidate.queue?.status === "notified" ? "Salvando" : "Enfileirando";
      try {
        if (candidate.queue?.status === "notified") {
          const result = await fetchJson(`/api/queue/${candidate.queue.queue_id}/mark-posted`, {
            method: "POST",
          });
          candidate.queue = result.queue;
          candidate.post = result.post;
        } else {
          const queueItem = await fetchJson(`/api/runs/${summary.run_id}/approve`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              candidate_rank: candidate.rank,
              caption: captionInput.value,
            }),
          });
          candidate.queue = queueItem;
          candidate.post = null;
        }
        applyQueueState(candidate, queueBadge, queueNote, approveButton);
      } catch (error) {
        approveButton.disabled = false;
        approveButton.textContent = candidate.queue?.status === "notified" ? "Marcar postado" : "Aprovar";
        queueBadge.dataset.state = "failed";
        queueBadge.textContent = "Falhou";
        queueNote.textContent = error.message;
      }
    });

    card.dataset.runId = summary.run_id;
    resultsGrid.appendChild(fragment);
  });
}

function renderRecentRuns(runs) {
  recentGrid.innerHTML = "";
  runs.forEach((run) => {
    const fragment = recentTemplate.content.cloneNode(true);
    const video = fragment.querySelector("video");
    const title = fragment.querySelector(".recent-title");
    const meta = fragment.querySelector(".recent-meta");
    const button = fragment.querySelector(".load-run-button");

    video.src = run.video_url;
    title.textContent = run.title;
    meta.textContent = `${run.uploader || "canal desconhecido"} · ${run.transcript_provider || "transcript"}`;
    button.addEventListener("click", () => loadRun(run.run_id));

    recentGrid.appendChild(fragment);
  });
}

async function refreshRecentRuns() {
  const runs = await fetchJson("/api/recent-runs");
  renderRecentRuns(runs);
}

async function loadRun(runId) {
  const summary = await fetchJson(`/api/runs/${runId}`);
  renderRun(summary);
}

async function pollJob(jobId) {
  try {
    const job = await fetchJson(`/api/jobs/${jobId}`);
    setStatus(job);

    if (job.status === "completed" && job.run_id) {
      clearInterval(activePoll);
      activePoll = null;
      submitButton.disabled = false;
      submitButton.textContent = "Gerar cortes";
      await loadRun(job.run_id);
      await refreshRecentRuns();
      return;
    }

    if (job.status === "failed") {
      clearInterval(activePoll);
      activePoll = null;
      submitButton.disabled = false;
      submitButton.textContent = "Gerar cortes";
      statusMessage.textContent = job.error || job.message || "Falha ao processar o video.";
    }
  } catch (error) {
    clearInterval(activePoll);
    activePoll = null;
    submitButton.disabled = false;
    submitButton.textContent = "Gerar cortes";
    statusPanel.classList.remove("hidden");
    statusText.textContent = "failed";
    statusMessage.textContent = error.message;
  }
}

topKInput.addEventListener("change", syncRenderCount);
renderTopKInput.addEventListener("change", syncRenderCount);

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  syncRenderCount();
  submitButton.disabled = true;
  submitButton.textContent = "Processando";
  resultsPanel.classList.add("hidden");

  const topK = Number(topKInput.value || 5);
  const payload = {
    url: document.getElementById("video-url").value,
    rights_status: document.getElementById("rights-status").value,
    top_k: topK,
    render_top_k: Math.max(Number(renderTopKInput.value || topK), topK),
    language: document.getElementById("language").value || null,
  };

  try {
    const job = await fetchJson("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    setStatus(job);

    if (activePoll) {
      clearInterval(activePoll);
    }
    activePoll = window.setInterval(() => {
      pollJob(job.job_id);
    }, 2200);
    pollJob(job.job_id);
  } catch (error) {
    submitButton.disabled = false;
    submitButton.textContent = "Gerar cortes";
    statusPanel.classList.remove("hidden");
    statusText.textContent = "failed";
    statusMessage.textContent = error.message;
  }
});

syncRenderCount();
refreshRecentRuns().catch(() => {});
