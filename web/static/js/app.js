/**
 * Easibot Web Dashboard Frontend Logic
 * Real-time SSE state synchronization, interactive multilingual chat, and hardware controls.
 */

document.addEventListener("DOMContentLoaded", () => {
    // DOM Elements
    const connDot = document.getElementById("header-conn-dot");
    const connText = document.getElementById("header-conn-text");
    const stateBadge = document.getElementById("robot-state-badge");
    const emotionVal = document.getElementById("robot-emotion-val");
    const langSelect = document.getElementById("active-lang-select");
    const speakerToggle = document.getElementById("speaker-toggle");
    
    const distanceNumber = document.getElementById("distance-number");
    const distanceBar = document.getElementById("distance-bar");
    const tftMirrorImg = document.getElementById("tft-mirror-img");
    
    const chatHistory = document.getElementById("chat-history");
    const chatForm = document.getElementById("chat-form");
    const userInput = document.getElementById("user-input");
    const speakReplyCheck = document.getElementById("speak-reply-check");
    const btnSend = document.getElementById("btn-send");
    
    const btnTriggerMic = document.getElementById("btn-trigger-mic");
    const micBtnText = document.getElementById("mic-btn-text");
    const btnTestApproach = document.getElementById("btn-test-approach");

    let isSSEConnected = false;
    let renderedMessageCount = 0;
    let tftRefreshTimer = null;

    // =========================================================================
    // Real-Time State Sync via Server-Sent Events (SSE) with Polling Fallback
    // =========================================================================
    function initEventStream() {
        if (!window.EventSource) {
            startPolling();
            return;
        }

        const evtSource = new EventSource("/api/stream");

        evtSource.onopen = () => {
            isSSEConnected = true;
            connDot.style.background = "#10b981";
            connDot.style.boxShadow = "0 0 8px #10b981";
            connText.textContent = "Live Connected";
        };

        evtSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                updateDashboard(data);
            } catch (err) {
                console.error("Error parsing SSE data:", err);
            }
        };

        evtSource.onerror = () => {
            isSSEConnected = false;
            connDot.style.background = "#f43f5e";
            connDot.style.boxShadow = "0 0 8px #f43f5e";
            connText.textContent = "Reconnecting...";
            evtSource.close();
            setTimeout(initEventStream, 3000);
        };
    }

    function startPolling() {
        setInterval(() => {
            fetch("/api/status")
                .then(res => res.json())
                .then(data => updateDashboard(data))
                .catch(err => console.debug("Status poll error:", err));
        }, 1000);
    }

    // =========================================================================
    // Dashboard UI Updates
    // =========================================================================
    function updateDashboard(data) {
        if (!data) return;

        // 1. Update State Badge
        const state = (data.state || "idle").toLowerCase();
        stateBadge.textContent = state.toUpperCase();
        stateBadge.className = `status-badge ${state}`;

        // 2. Update Emotion
        emotionVal.textContent = data.emotion || "neutral";

        // 3. Update Ultrasonic Distance Meter
        const dist = data.distance_cm;
        if (dist !== undefined && dist >= 0) {
            distanceNumber.textContent = dist.toFixed(0);
            // Calculate percentage of 200cm
            const pct = Math.min(100, Math.max(2, (dist / 200.0) * 100));
            distanceBar.style.width = `${pct}%`;

            // Change bar color if inside wake threshold
            if (dist <= 60.0) {
                distanceBar.style.background = "#f43f5e";
            } else {
                distanceBar.style.background = "linear-gradient(90deg, #10b981 0%, #00d4ff 50%, #f59e0b 85%)";
            }
        } else {
            distanceNumber.textContent = "--";
            distanceBar.style.width = "0%";
        }

        // 4. Update Mic button state
        if (state === "listening") {
            btnTriggerMic.classList.add("recording");
            micBtnText.textContent = "Listening to Voice...";
        } else if (state === "thinking") {
            btnTriggerMic.classList.remove("recording");
            micBtnText.textContent = "AI Thinking & Translating...";
        } else if (state === "speaking") {
            btnTriggerMic.classList.remove("recording");
            micBtnText.textContent = "Speaking on Speaker...";
        } else {
            btnTriggerMic.classList.remove("recording");
            micBtnText.textContent = "Trigger Voice Listen";
        }

        // 5. Update Messages if new ones arrived
        if (data.messages && data.messages.length > renderedMessageCount) {
            renderMessages(data.messages);
            renderedMessageCount = data.messages.length;
        }
    }

    // =========================================================================
    // TFT Mirror Refresh Loop
    // =========================================================================
    function refreshTFTMirror() {
        if (tftMirrorImg) {
            tftMirrorImg.src = `/api/tft_preview?t=${Date.now()}`;
        }
    }
    // Refresh mirror every 600ms
    tftRefreshTimer = setInterval(refreshTFTMirror, 600);

    // =========================================================================
    // Chat Message Rendering
    // =========================================================================
    function renderMessages(messages) {
        chatHistory.innerHTML = "";
        messages.forEach(msg => {
            const isBot = msg.sender === "robot";
            const bubble = document.createElement("div");
            bubble.className = `chat-bubble ${isBot ? "bot-bubble" : "user-bubble"}`;

            const langCode = (msg.language || "en").toUpperCase();

            let translationHtml = "";
            if (isBot && (msg.english || msg.romanized) && msg.language !== "en") {
                translationHtml = `
                    <div class="translation-card">
                        ${msg.english ? `<div class="text-english"><span class="trans-label">EN:</span> ${escapeHtml(msg.english)}</div>` : ""}
                        ${msg.romanized ? `<div class="text-romanized"><span class="trans-label">Pronunciation:</span> ${escapeHtml(msg.romanized)}</div>` : ""}
                    </div>
                `;
            }

            bubble.innerHTML = `
                <div class="bubble-header">
                    <span class="sender-tag">${isBot ? "EASIBOT" : "YOU"}</span>
                    <span class="lang-tag">${langCode}</span>
                    <span class="time-tag">${msg.timestamp || ""}</span>
                </div>
                <div class="bubble-content">
                    <p class="text-native">${escapeHtml(msg.text)}</p>
                    ${translationHtml}
                </div>
            `;
            chatHistory.appendChild(bubble);
        });

        // Scroll to bottom
        chatHistory.scrollTop = chatHistory.scrollHeight;
    }

    function escapeHtml(text) {
        if (!text) return "";
        const div = document.createElement("div");
        div.textContent = text;
        return div.innerHTML;
    }

    // =========================================================================
    // Form & Controls Interactivity
    // =========================================================================
    chatForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const text = userInput.value.trim();
        if (!text) return;

        const lang = langSelect.value;
        const speakOnRobot = speakReplyCheck.checked;

        // Optimistically add user message to list
        userInput.value = "";
        btnSend.disabled = true;

        try {
            const res = await fetch("/api/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    message: text,
                    language: lang,
                    speak_on_robot: speakOnRobot
                })
            });
            const data = await res.json();
            if (data.status === "error") {
                alert(`Error: ${data.message}`);
            }
        } catch (err) {
            console.error("Error sending message:", err);
        } finally {
            btnSend.disabled = false;
            userInput.focus();
        }
    });

    // Quick Prompt Chips
    document.querySelectorAll(".chip").forEach(chip => {
        chip.addEventListener("click", () => {
            const query = chip.getAttribute("data-text");
            if (query) {
                userInput.value = query;
                chatForm.dispatchEvent(new Event("submit"));
            }
        });
    });

    // Language Dropdown
    langSelect.addEventListener("change", async () => {
        try {
            await fetch("/api/set_language", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ language: langSelect.value })
            });
        } catch (err) {
            console.error("Failed to set language:", err);
        }
    });

    // Speaker Toggle
    speakerToggle.addEventListener("change", async () => {
        try {
            await fetch("/api/toggle_speaker", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ enabled: speakerToggle.checked })
            });
        } catch (err) {
            console.error("Failed to toggle speaker:", err);
        }
    });

    // Trigger Voice Listen
    btnTriggerMic.addEventListener("click", async () => {
        btnTriggerMic.disabled = true;
        try {
            await fetch("/api/trigger_listen", { method: "POST" });
        } catch (err) {
            console.error("Failed to trigger voice listen:", err);
        } finally {
            setTimeout(() => { btnTriggerMic.disabled = false; }, 4000);
        }
    });

    // Test Proximity Person Approach (Mock mode test)
    btnTestApproach.addEventListener("click", async () => {
        try {
            await fetch("/api/mock/distance", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ distance_cm: 42.0 })
            });
        } catch (err) {
            console.error("Failed to set test distance:", err);
        }
    });

    // Start Real-Time SSE
    initEventStream();
});
