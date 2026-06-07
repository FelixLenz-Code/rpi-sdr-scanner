# ui/web.py – vollständige Flask Web-UI mit SSE

import json
import threading
import logging
import queue

import config.settings as cfg

log = logging.getLogger(__name__)

_HTML = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SDR Scanner</title>
<style>
:root{
  --bg:#0a0c14;--card:#111827;--brd:#1e2d40;
  --pri:#00c8a0;--dim:#283748;--txt:#dce6f0;--mut:#607080;
  --act:#00dc64;--scan:#ffb400;--warn:#dc3c3c;--pur:#8b5cf6;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--txt);font-family:monospace;font-size:14px}
a{color:var(--pri);text-decoration:none}

/* Layout */
.layout{display:grid;grid-template-columns:300px 1fr;min-height:100vh}
.sidebar{background:var(--card);border-right:1px solid var(--brd);padding:1rem;display:flex;flex-direction:column;gap:.75rem;height:100vh;overflow-y:auto;position:sticky;top:0}
.main{padding:1rem;display:flex;flex-direction:column;gap:1rem;overflow-x:hidden;min-width:0}

/* Cards */
.card{background:var(--card);border:1px solid var(--brd);border-radius:8px;overflow:hidden}
.card-head{padding:.5rem .75rem;border-bottom:1px solid var(--brd);font-size:12px;color:var(--mut);text-transform:uppercase;letter-spacing:.05em;display:flex;justify-content:space-between;align-items:center}
.card-body{padding:.75rem}

/* Status pill */
.pill{display:inline-block;padding:2px 10px;border-radius:99px;font-size:11px;font-weight:bold}
.pill-idle{background:var(--dim);color:var(--txt)}
.pill-scan{background:var(--scan);color:#000}
.pill-act{background:var(--act);color:#000}
.pill-bank{background:var(--pur);color:#fff}

/* Frequenz-Anzeige */
#freq{font-size:2rem;font-weight:bold;letter-spacing:2px;color:var(--txt);line-height:1}
#ch-name{font-size:1.1rem;color:var(--pri);margin:.25rem 0;cursor:pointer;display:flex;align-items:center;gap:.4rem;overflow:hidden}
#ch-name span:first-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#ch-name:hover span{border-bottom:1px solid var(--pri)}
#meta{font-size:12px;color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

/* Kanalwechsel-Animation beim Scan */
@keyframes scan-step {
  from { opacity:.3; transform:translateY(-5px) }
  to   { opacity:1;  transform:translateY(0) }
}
#freq.scanning { color:var(--scan) }
#ch-name.scanning { color:var(--scan) !important }
#ch-name.scanning .rename-hint { display:none }
.freq-step { animation:scan-step .14s ease-out }

/* Signal-Balken */
.bars{display:flex;align-items:flex-end;gap:3px;height:22px}
.bar{width:8px;border-radius:2px 2px 0 0;background:var(--dim)}
.bar.on{background:var(--act)}
#rssi-val{font-size:12px;color:var(--mut)}

/* Controls */
.btn-row{display:flex;flex-wrap:wrap;gap:.4rem}
button{background:var(--dim);color:var(--txt);border:1px solid var(--brd);
       padding:.35rem .75rem;border-radius:5px;cursor:pointer;font-family:monospace;font-size:13px}
button:hover{background:#304050}
button.pri{background:var(--pri);color:#000;border-color:var(--pri)}
button.pri:hover{opacity:.85}
button.warn{background:var(--warn);color:#fff;border-color:var(--warn)}
button.warn:hover{opacity:.85}
button.active-btn{border-color:var(--act);color:var(--act)}

/* Slider */
.slider-row{display:flex;align-items:center;gap:.5rem;margin:.3rem 0}
.slider-row label{width:60px;font-size:12px;color:var(--mut);flex-shrink:0}
.slider-row input[type=range]{flex:1;min-width:0;accent-color:var(--pri)}
.slider-row .val{min-width:52px;text-align:right;font-size:13px;white-space:nowrap;flex-shrink:0}

/* Freq-Input */
.freq-input-row{display:flex;gap:.4rem;align-items:center;flex-wrap:wrap}
.freq-input-row input{background:#1a2535;color:var(--txt);border:1px solid var(--brd);
                      border-radius:5px;padding:.3rem .5rem;font-family:monospace;font-size:15px;
                      flex:1;min-width:80px}
.freq-input-row select{background:#1a2535;color:var(--txt);border:1px solid var(--brd);
                        border-radius:5px;padding:.3rem .4rem;font-family:monospace;font-size:13px;flex-shrink:0}

/* Kanalliste */
table{width:100%;border-collapse:collapse;font-size:13px}
td,th{padding:.3rem .5rem;border-bottom:1px solid var(--brd);text-align:left;white-space:nowrap}
th{color:var(--mut);font-size:11px;text-transform:uppercase}
tr:hover td{background:#151e2c}
td.name-cell{cursor:pointer;max-width:160px;overflow:hidden;text-overflow:ellipsis}
td.name-cell:hover{color:var(--pri)}
.tune-btn{padding:2px 6px;font-size:11px}

/* Bank-Manager */
.bank-tab{padding:.25rem .55rem;border-radius:4px;cursor:pointer;font-size:12px;
          border:1px solid var(--brd);background:var(--dim);font-family:monospace;white-space:nowrap}
.bank-tab:hover{border-color:var(--pri)}
.bank-tab.viewing{border-color:var(--pri);color:var(--pri);background:#091822}
.bank-tab.in-scanner{border-color:var(--act)}
.bank-tab.viewing.in-scanner{background:var(--pri);color:#000;border-color:var(--pri)}



/* Inline-Edit */
.edit-input{background:#1a2535;color:var(--txt);border:1px solid var(--pri);
            border-radius:4px;padding:2px 6px;font-family:monospace;font-size:13px;width:100%}


/* Modal */
.modal-bg{position:absolute;inset:0;background:rgba(0,0,0,.7);display:flex;align-items:center;justify-content:center;z-index:100}
.modal{background:var(--card);border:1px solid var(--brd);border-radius:10px;padding:1.25rem;width:340px;max-width:95vw}
.modal h3{font-size:14px;margin-bottom:.75rem;color:var(--pri)}
.field{margin-bottom:.6rem}
.field label{display:block;font-size:11px;color:var(--mut);margin-bottom:2px}
.field input,.field select{width:100%;background:#1a2535;color:var(--txt);border:1px solid var(--brd);border-radius:5px;padding:.3rem .5rem;font-family:monospace;font-size:13px}
.field select option{background:#1a2535}
.modal-btns{display:flex;gap:.5rem;margin-top:.75rem;justify-content:flex-end}
/* Toast */
#toast{position:fixed;bottom:1.2rem;right:1.2rem;background:var(--pri);color:#000;
       padding:.4rem 1rem;border-radius:6px;font-size:13px;opacity:0;
       transition:opacity .25s;pointer-events:none;z-index:999}
#toast.err{background:var(--warn);color:#fff}
#toast.show{opacity:1}

/* Responsive */
@media(max-width:680px){
  .layout{grid-template-columns:1fr}
  .sidebar{height:auto;position:static;overflow-y:visible;border-right:none;border-bottom:1px solid var(--brd)}
}
</style>
</head>
<body>
<div class="layout">

<!-- ── Sidebar: Status + Hauptsteuerung ── -->
<div class="sidebar">

  <div>
    <div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.5rem;flex-wrap:wrap">
      <span id="state-pill" class="pill pill-idle">BEREIT</span>
      <span id="sdr-pill" class="pill" style="background:var(--dim);color:var(--mut)">SDR …</span>
      <span style="font-size:11px;color:var(--mut)" id="bank-label">B0</span>
    </div>
    <div id="freq">–</div>
    <div id="ch-name" onclick="renameActive()" title="Klicken zum Umbenennen">
      <span id="name-label">–</span><span class="rename-hint" style="font-size:11px;color:var(--mut)">✏</span>
    </div>
    <div id="meta" style="margin-bottom:.5rem">–</div>
    <div style="display:flex;align-items:center;gap:.6rem">
      <div class="bars" id="bars"></div>
      <span id="rssi-val">–</span>
    </div>
  </div>

  <!-- Scan + Mode -->
  <div class="card">
    <div class="card-head">Scanner</div>
    <div class="card-body" style="display:flex;flex-direction:column;gap:.5rem">
      <div class="btn-row">
        <button id="scan-btn" onclick="cmd('SCAN_TOGGLE')" class="pri" style="flex:1">&#9654; Scan</button>
        <button id="mode-btn" onclick="cmd('MODE')" style="flex:1">NFM</button>
        <button id="agc-btn" onclick="cmd('AGC_TOGGLE')" style="flex:1" title="Hardware-Gain: auto (AGC) oder manuell">AGC</button>
      </div>
      <div class="btn-row">
        <button onclick="cmd('ENC_DOWN')" style="flex:1">&#9650; Kanal</button>
        <button onclick="cmd('ENC_UP')"  style="flex:1">&#9660; Kanal</button>
      </div>
      <button onclick="openSaveModal()" class="pri" style="width:100%">&#128190; Frequenz speichern …</button>
      <button onclick="cmd('CALIBRATE')" style="width:100%" title="PPM-Kalibrierung starten">&#9881; PPM-Kalibrierung</button>
      <div id="calib-log" style="display:none;border:1px solid #333;border-radius:4px;margin-top:.2rem">
        <div style="display:flex;justify-content:space-between;align-items:center;padding:.25rem .5rem;border-bottom:1px solid #333;border-radius:4px 4px 0 0;background:#111;font-size:11px;color:var(--mut)">
          <span>Kalibrierungslog</span>
          <button id="calib-log-close" onclick="_calibLogDismissed=true;document.getElementById('calib-log').style.display='none'" style="font-size:11px;padding:.1rem .4rem;display:none">✕</button>
        </div>
        <pre id="calib-log-text" style="margin:0;padding:.4rem .6rem;font-size:.75rem;background:#111;color:#ccc;line-height:1.5;white-space:pre-wrap;overflow-wrap:anywhere;max-height:90px;overflow-y:auto;border-radius:0 0 4px 4px"></pre>
      </div>
    </div>
  </div>

  <!-- Direkt-Abstimmung -->
  <div class="card">
    <div class="card-head">Frequenz direkt</div>
    <div class="card-body">
      <div class="freq-input-row">
        <input type="text" id="freq-input" placeholder="155.325" title="MHz eingeben"/>
        <select id="mode-sel">
          <option>NFM</option><option>FM</option><option>WFM</option><option>AM</option>
        </select>
        <button onclick="tuneManual()" class="pri">Go</button>
      </div>
      <div style="font-size:11px;color:var(--mut);margin-top:.3rem">MHz eingeben, dann Go</div>
    </div>
  </div>

  <!-- Squelch + Lautstärke -->
  <div class="card">
    <div class="card-head">Audio</div>
    <div class="card-body">
      <div class="slider-row">
        <label>Squelch</label>
        <input type="range" min="-120" max="0" step="1" id="sq-slider" oninput="setSq(this.value)">
        <span class="val" id="sq-val">–</span>
      </div>
      <div class="btn-row" style="margin-bottom:.4rem">
        <button onclick="cmd('SQ_DOWN')" style="flex:1">SQ −</button>
        <button onclick="cmd('SQ_UP')"   style="flex:1">SQ +</button>
      </div>
      <div class="slider-row">
        <label>Volume</label>
        <input type="range" min="0" max="100" step="5" id="vol-slider" oninput="setVol(this.value)">
        <span class="val" id="vol-val">–</span>
      </div>
      <div class="btn-row">
        <button onclick="setVol(0)"   style="flex:1">Mute</button>
        <button onclick="setVol(50)"  style="flex:1">50%</button>
        <button onclick="setVol(100)" style="flex:1">Max</button>
      </div>
      <div class="slider-row" style="margin-top:.4rem">
        <label>Gain</label>
        <input type="range" min="0" max="100" step="1" id="gain-slider" oninput="setGain(parseFloat(this.value))">
        <span class="val" id="gain-val">–</span>
      </div>
      <label style="font-size:12px;display:flex;align-items:center;gap:.4rem;margin-top:.5rem;cursor:pointer;color:var(--mut)">
        <input type="checkbox" id="comp-check" onchange="setComp(this.checked)">
        Kompressor (aus bei WFM)
      </label>
    </div>
  </div>

  <!-- Hotspot / WLAN -->
  <div class="card">
    <div class="card-head">
      <span>WLAN-Hotspot</span>
      <span id="hotspot-status" style="font-size:11px;padding:2px 7px;border-radius:99px;background:var(--dim);color:var(--txt)">inaktiv</span>
    </div>
    <div class="card-body" style="display:flex;flex-direction:column;gap:.5rem">
      <div style="font-size:12px;color:var(--mut)">
        SSID: <span id="hotspot-ssid" style="color:var(--txt)">SDR-Scanner</span>
      </div>
      <div style="font-size:12px;color:var(--mut)">
        Adresse: <a href="http://192.168.4.1:5000" style="color:var(--pri)">192.168.4.1:5000</a>
      </div>
      <button onclick="showWifiSettings()" style="width:100%">WLAN-Einstellungen</button>
    </div>
  </div>

</div>

<!-- ── Hauptbereich ── -->
<div class="main">

  <!-- Memory-Bänke Manager -->
  <div class="card">
    <div class="card-head">
      Memory-Bänke
      <div style="display:flex;gap:.3rem">
        <button onclick="exportBanks()" style="font-size:11px;padding:2px 8px">&#11015; Export</button>
        <label style="font-size:11px;padding:2px 8px;background:var(--dim);border:1px solid var(--brd);border-radius:5px;cursor:pointer;font-family:monospace;color:var(--txt)">
          &#11014; Import<input type="file" accept=".json" onchange="importBanks(this)" style="display:none">
        </label>
      </div>
    </div>
    <!-- Tab-Leiste -->
    <div id="bank-tab-bar" style="padding:.4rem .6rem;border-bottom:1px solid var(--brd);display:flex;flex-wrap:wrap;gap:.3rem"></div>
    <!-- Aktionszeile -->
    <div style="padding:.4rem .75rem;border-bottom:1px solid var(--brd);display:flex;align-items:center;gap:.4rem;flex-wrap:wrap;min-height:2.4rem">
      <span id="bpanel-title" style="font-weight:bold;color:var(--txt);flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px">–</span>
      <button onclick="bankRenamePrompt()" style="font-size:11px;padding:2px 8px;flex-shrink:0">&#9998; Umbenennen</button>
    </div>
    <!-- Kanaltabelle -->
    <div style="overflow-x:auto">
      <table id="bpanel-table" style="display:none;min-width:360px">
        <thead><tr><th>#</th><th>Name</th><th>MHz</th><th>Mode</th><th>BW</th><th></th></tr></thead>
        <tbody id="bpanel-tbody"></tbody>
      </table>
      <div id="bpanel-empty" style="padding:.75rem;font-size:12px;color:var(--mut)">Keine Kanäle in dieser Bank.</div>
    </div>
  </div>

</div>
</div>

<!-- Modal: Frequenz speichern -->
<div id="save-modal-bg" class="modal-bg" style="display:none">
  <div class="modal">
    <h3>Frequenz speichern</h3>
    <div id="save-freq-display" style="font-size:1.3rem;font-weight:bold;color:var(--pri);text-align:center;margin-bottom:.75rem;letter-spacing:1px">–</div>
    <div class="field">
      <label>Name</label>
      <input id="save-ch-name" type="text" placeholder="z.B. Feuerwehr Leitstelle">
    </div>
    <div class="field">
      <label>In Bank speichern</label>
      <select id="save-bank-sel"></select>
    </div>
    <div class="modal-btns">
      <button onclick="closeSaveModal()">Abbrechen</button>
      <button class="pri" onclick="submitSave()">Speichern</button>
    </div>
  </div>
</div>

<!-- Modal: Kanal bearbeiten -->
<div id="ch-edit-modal-bg" class="modal-bg" style="display:none">
  <div class="modal">
    <h3>Kanal bearbeiten</h3>
    <input type="hidden" id="ch-edit-id">
    <div class="field"><label>Name</label>
      <input id="ch-edit-name" type="text" placeholder="z.B. Feuerwehr 1">
    </div>
    <div class="field"><label>Frequenz (MHz)</label>
      <input id="ch-edit-freq" type="number" step="0.0001" min="0.1" max="2000" placeholder="155.3250">
    </div>
    <div class="field"><label>Modus</label>
      <select id="ch-edit-mode" onchange="fillBwSelect(this.value, null)">
        <option>NFM</option><option>FM</option><option>WFM</option><option>AM</option>
      </select>
    </div>

    <div class="field">
      <label>Gain <span id="ch-edit-gain-val" style="font-weight:normal;color:var(--mut)">Standard</span></label>
      <div class="slider-row">
        <input type="range" min="0" max="100" step="1" id="ch-edit-gain"
               oninput="chEditGainUpdate(this.value)">
        <button style="font-size:11px;padding:.1rem .4rem" onclick="chEditGainReset()" title="Auf Standard zurücksetzen">↺</button>
      </div>
    </div>
    <div class="field"><label>Squelch</label>
      <div class="slider-row">
        <input type="range" min="-120" max="0" step="1" id="ch-edit-sq"
               oninput="document.getElementById('ch-edit-sq-val').textContent=this.value+' dB'">
        <span class="val" id="ch-edit-sq-val">–</span>
      </div>
    </div>
    <div class="field"><label>Kanalbandbreite</label>
      <select id="ch-edit-bw" onchange="bwSelectChange(this)"></select>
      <div id="ch-edit-bw-manual-row" style="display:none;margin-top:.3rem;display:none">
        <div style="display:flex;align-items:center;gap:.4rem">
          <input id="ch-edit-bw-manual" type="number" min="100" max="500000" step="100"
                 placeholder="z.B. 8330" style="flex:1"
                 oninput="document.getElementById('ch-edit-bw-khz').textContent=(this.value>=1000?(this.value/1000).toFixed(2)+' kHz':this.value+' Hz')">
          <span style="font-size:12px;color:var(--mut);flex-shrink:0">Hz</span>
        </div>
        <div style="font-size:11px;color:var(--mut);margin-top:2px" id="ch-edit-bw-khz"></div>
      </div>
    </div>
    <div class="modal-btns">
      <button onclick="closeChEditModal()">Abbrechen</button>
      <button class="pri" onclick="submitChEdit()">Speichern</button>
    </div>
  </div>
</div>

<!-- Modal: WLAN-Einstellungen -->
<div id="wifi-modal-bg" class="modal-bg" style="display:none">
  <div class="modal">
    <h3>WLAN-Hotspot ändern</h3>
    <div class="field">
      <label>SSID (Netzwerkname)</label>
      <input id="wifi-ssid" type="text" placeholder="SDR-Scanner" maxlength="32">
    </div>
    <div class="field">
      <label>Passwort (min. 8 Zeichen)</label>
      <input id="wifi-pass" type="password" placeholder="sdrscanner">
      <label style="margin-top:4px;font-size:11px;display:flex;align-items:center;gap:.3rem">
        <input type="checkbox" onchange="this.parentElement.previousElementSibling.type=this.checked?'text':'password'">
        Passwort anzeigen
      </label>
    </div>
    <div style="font-size:11px;color:var(--mut);margin:.3rem 0">
      Änderung trennt alle Verbindungen. Pi kurz neu verbinden.
    </div>
    <div class="modal-btns">
      <button onclick="closeWifiModal()">Abbrechen</button>
      <button class="pri" onclick="submitWifiSettings()">Übernehmen</button>
    </div>
  </div>
</div>

<div id="toast"></div>

<script>
let _state = {};
let _sqPending = false;
let _volPending = false;
let _gainPending = false;
let _lastScanFreq = '';
let _chEditGainNull = false;  // true = Slider auf "Standard" gesetzt
let _calibLogDismissed = false;

// ── SSE Live-Update ──────────────────────────────────────────────────────────
const src = new EventSource('/events');
src.onmessage = e => {
  const d = JSON.parse(e.data);
  _state = d;
  updateStatus(d);
  updateBankTabs(d.bank_summary || [], d.loaded_bank ?? null);
};
src.onerror = () => console.warn('SSE unterbrochen');

function updateStatus(d) {
  const isScanning = d.scanning || d.state === 'SCANNING';
  const freqEl  = document.getElementById('freq');
  const cnameEl = document.getElementById('ch-name');
  const nameEl  = document.getElementById('name-label');

  freqEl.textContent = d.freq_mhz + ' MHz';
  nameEl.textContent = d.channel.split('(')[0].trim();

  if (isScanning) {
    freqEl.classList.add('scanning');
    cnameEl.classList.add('scanning');
    if (d.freq_mhz !== _lastScanFreq) {
      _lastScanFreq = d.freq_mhz;
      freqEl.classList.remove('freq-step');
      void freqEl.offsetWidth;          // Reflow → Animation neu starten
      freqEl.classList.add('freq-step');
    }
  } else {
    freqEl.classList.remove('scanning', 'freq-step');
    cnameEl.classList.remove('scanning');
    _lastScanFreq = '';
  }

  const modeBw = {NFM:12500, FM:25000, WFM:200000, AM:10000};
  const bwHz = d.bandwidth != null ? d.bandwidth : (modeBw[d.mode] ?? null);
  const bwLabel = bwHz != null
    ? (bwHz >= 1000 ? (bwHz/1000).toFixed(1)+'kHz' : bwHz+'Hz')
    : '–';
  document.getElementById('meta').textContent =
    d.mode + '  ·  ' + bwLabel + '  ·  ' + (d.ch_index+1) + '/' + d.ch_total;
  const lbId = d.loaded_bank;
  const lbName = lbId != null
    ? (d.bank_summary || []).find(b => b.bank === lbId)?.name || ''
    : null;
  document.getElementById('bank-label').textContent =
    lbId != null ? ('B' + lbId + ' – ' + lbName) : 'Std';
  document.getElementById('rssi-val').textContent = d.rssi.toFixed(0) + ' dBFS';

  const pill = document.getElementById('state-pill');
  const labels = {IDLE:'BEREIT',SCANNING:'SCAN…',ACTIVE:'EMPFANG',
                  BANK_SELECT:'BANK',MENU:'MENÜ'};
  const classes = {IDLE:'pill-idle',SCANNING:'pill-scan',ACTIVE:'pill-act',
                   BANK_SELECT:'pill-bank',MENU:'pill-bank'};
  pill.textContent = labels[d.state] || d.state;
  pill.className = 'pill ' + (classes[d.state] || 'pill-idle');

  const scanBtn = document.getElementById('scan-btn');
  scanBtn.textContent = isScanning ? '⏹ Stop' : '▶ Scan';

  const bars = document.getElementById('bars');
  bars.innerHTML = '';
  for (let i = 0; i < 5; i++) {
    const b = document.createElement('div');
    b.className = 'bar' + (i < d.signal_bar ? ' on' : '');
    b.style.height = (8 + i * 3) + 'px';
    bars.appendChild(b);
  }

  const sdrPill = document.getElementById('sdr-pill');
  if (d.dongle_ok) {
    sdrPill.textContent = 'SDR OK';
    sdrPill.style.background = 'var(--act)';
    sdrPill.style.color = '#000';
  } else {
    sdrPill.textContent = 'Kein SDR';
    sdrPill.style.background = 'var(--warn)';
    sdrPill.style.color = '#fff';
  }

  const compCheck = document.getElementById('comp-check');
  if (compCheck && !compCheck._changing) compCheck.checked = !!d.comp_enabled;

  const agcBtn = document.getElementById('agc-btn');
  if (agcBtn) {
    agcBtn.textContent = d.agc_enabled ? 'AGC ●' : 'AGC';
    agcBtn.className = d.agc_enabled ? 'active-btn' : '';
  }

  const modeBtn = document.getElementById('mode-btn');
  if (modeBtn) modeBtn.textContent = d.mode || 'NFM';

  const calibLog = document.getElementById('calib-log');
  if (calibLog) {
    const lines = d.calib_log || [];
    if (d.state === 'CALIBRATING') _calibLogDismissed = false;
    if (lines.length > 0 && !_calibLogDismissed) {
      const pre = document.getElementById('calib-log-text');
      pre.textContent = lines.join('\n');
      pre.scrollTop = pre.scrollHeight;
      calibLog.style.display = 'block';
      document.getElementById('calib-log-close').style.display =
        d.state !== 'CALIBRATING' ? 'inline-block' : 'none';
    } else if (lines.length === 0) {
      calibLog.style.display = 'none';
      _calibLogDismissed = false;
    }
  }

  // Slider nur aktualisieren wenn gerade nicht gedreht wird
  if (!_sqPending) {
    const s = document.getElementById('sq-slider');
    s.value = d.sq_level;
    document.getElementById('sq-val').textContent = d.sq_level + ' dB';
  }
  if (!_volPending) {
    const v = document.getElementById('vol-slider');
    v.value = d.volume;
    document.getElementById('vol-val').textContent = d.volume + '%';
  }
  if (!_gainPending) {
    const g = document.getElementById('gain-slider');
    if (g) {
      g.value = d.audio_gain ?? 20;
      document.getElementById('gain-val').textContent = '×' + (d.audio_gain ?? 20).toFixed(0);
    }
  }

  const hsPill = document.getElementById('hotspot-status');
  if (hsPill && d.hotspot_on !== undefined) {
    if (d.hotspot_busy) {
      hsPill.textContent = 'einrichten…';
      hsPill.style.background = 'var(--warn)';
      hsPill.style.color = '#000';
    } else if (d.hotspot_on) {
      hsPill.textContent = 'aktiv';
      hsPill.style.background = 'var(--act)';
      hsPill.style.color = '#000';
    } else {
      hsPill.textContent = 'inaktiv';
      hsPill.style.background = 'var(--dim)';
      hsPill.style.color = 'var(--txt)';
    }
  }
}

// ── Memory-Bänke ─────────────────────────────────────────────────────────────
let _viewBankId = 0;
let _bankSummary = [];

function updateBankTabs(summary, loadedBank) {
  _bankSummary = summary;
  // Beim ersten Update _viewBankId auf die aktive Bank setzen
  if (loadedBank !== null && loadedBank !== undefined) _viewBankId = loadedBank;
  const bar = document.getElementById('bank-tab-bar');
  bar.innerHTML = '';
  summary.forEach(b => {
    const btn = document.createElement('button');
    const isActive = b.bank === (loadedBank ?? _viewBankId);
    btn.className = 'bank-tab' + (isActive ? ' viewing in-scanner' : '');
    btn.textContent = 'B' + b.bank + (b.count ? ' · ' + b.count : '');
    btn.title = b.name;
    btn.dataset.bank = b.bank;
    btn.onclick = () => viewBank(b.bank);
    bar.appendChild(btn);
  });
  const b = summary.find(x => x.bank === _viewBankId);
  if (b) {
    document.getElementById('bpanel-title').textContent = 'B' + b.bank + ': ' + b.name;
  }
}

// Nur anzeigen – lädt NICHT in den Scanner
function viewBank(bankId) {
  _viewBankId = bankId;
  document.querySelectorAll('.bank-tab').forEach(btn => {
    btn.classList.toggle('viewing', parseInt(btn.dataset.bank) === bankId);
  });
  const b = _bankSummary.find(x => x.bank === bankId);
  if (b) document.getElementById('bpanel-title').textContent = 'B' + b.bank + ': ' + b.name;
  refreshBankChannels();
  loadBank(bankId);   // Bank direkt in Scanner laden – kein separater Schritt nötig
}

// Explizit in den Scanner laden
function loadBank(bankId) {
  fetch('/bank/load/' + bankId, {method:'POST'})
    .then(r => r.ok ? toast('Bank ' + bankId + ' in Scanner geladen') : toast('Fehler', true));
}

function refreshBankChannels() {
  fetch('/banks/' + _viewBankId + '/channels')
    .then(r => r.json())
    .then(renderBankChannels)
    .catch(() => {});
}

function renderBankChannels(chs) {
  const tbody   = document.getElementById('bpanel-tbody');
  const empty   = document.getElementById('bpanel-empty');
  const table   = document.getElementById('bpanel-table');
  tbody.innerHTML = '';
  if (!chs.length) {
    table.style.display = 'none';
    empty.style.display = 'block';
    return;
  }
  table.style.display = '';
  empty.style.display = 'none';
  chs.forEach((ch, i) => {
    const tr = document.createElement('tr');

    const nameTd = document.createElement('td');
    nameTd.className = 'name-cell';
    nameTd.textContent = ch.name;
    nameTd.onclick = () => startBankChannelEdit(nameTd, ch.id, ch.name);

    const actTd = document.createElement('td');
    actTd.style.whiteSpace = 'nowrap';
    const mkBtn = (label, title, color, cb) => {
      const b = document.createElement('button');
      b.className = 'tune-btn';
      b.title = title;
      b.innerHTML = label;
      if (color) b.style.color = color;
      b.onclick = cb;
      return b;
    };
    actTd.appendChild(mkBtn('&#9658;', 'Abstimmen',  null,           () => bankTuneChannel(ch)));
    actTd.appendChild(document.createTextNode(' '));
    actTd.appendChild(mkBtn('&#9998;', 'Bearbeiten', null,           () => openChEditModal(ch)));
    actTd.appendChild(document.createTextNode(' '));
    actTd.appendChild(mkBtn('&times;', 'Löschen',    'var(--warn)',  () => deleteBankChannel(ch.id)));

    const bwTd = document.createElement('td');
    bwTd.style.fontSize = '11px';
    bwTd.style.color = 'var(--mut)';
    bwTd.textContent = ch.bandwidth != null ? (ch.bandwidth >= 1000 ? (ch.bandwidth/1000).toFixed(1)+'k' : ch.bandwidth+'Hz') : '–';

    tr.appendChild(Object.assign(document.createElement('td'), {textContent: i+1}));
    tr.appendChild(nameTd);
    tr.appendChild(Object.assign(document.createElement('td'), {textContent: (ch.freq/1e6).toFixed(4)}));
    tr.appendChild(Object.assign(document.createElement('td'), {textContent: ch.mode}));
    tr.appendChild(bwTd);
    tr.appendChild(actTd);
    tbody.appendChild(tr);
  });
}

function startBankChannelEdit(td, chId, cur) {
  const inp = document.createElement('input');
  inp.className = 'edit-input';
  inp.value = cur;
  td.textContent = '';
  td.appendChild(inp);
  inp.focus(); inp.select();
  const commit = () => {
    const n = inp.value.trim();
    if (n && n !== cur) {
      fetch('/banks/channels/' + chId + '/rename', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({name: n})
      }).then(r => { td.textContent = r.ok ? n : cur; if (r.ok) toast('Umbenannt'); });
    } else { td.textContent = cur; }
  };
  inp.onblur = commit;
  inp.onkeydown = e => { if (e.key==='Enter') inp.blur(); if (e.key==='Escape') { td.textContent=cur; } };
}

const BW_OPTIONS = {
  NFM: [[null,'Standard (12.5 kHz)'],[6250,'6.25 kHz'],[12500,'12.5 kHz'],[20000,'20 kHz'],[25000,'25 kHz'],['manual','Manuell …']],
  FM:  [[null,'Standard (25 kHz)'],[12500,'12.5 kHz'],[25000,'25 kHz'],['manual','Manuell …']],
  WFM: [[null,'Standard (200 kHz)'],[75000,'75 kHz'],[150000,'150 kHz'],[200000,'200 kHz'],['manual','Manuell …']],
  AM:  [[null,'Standard (10 kHz)'],[6000,'6 kHz'],[8000,'8 kHz'],[8330,'8.33 kHz'],[10000,'10 kHz'],[16000,'16 kHz'],['manual','Manuell …']],
};
function _bwManualShow(show, val) {
  const row = document.getElementById('ch-edit-bw-manual-row');
  const inp = document.getElementById('ch-edit-bw-manual');
  const lbl = document.getElementById('ch-edit-bw-khz');
  row.style.display = show ? 'block' : 'none';
  if (show && val != null) {
    inp.value = val;
    lbl.textContent = val >= 1000 ? (val/1000).toFixed(2)+' kHz' : val+' Hz';
  } else if (show) {
    inp.value = '';
    lbl.textContent = '';
  }
}
function fillBwSelect(mode, selected) {
  const sel = document.getElementById('ch-edit-bw');
  sel.innerHTML = '';
  const opts = BW_OPTIONS[mode] || [[null,'Standard'],['manual','Manuell …']];
  const knownVals = opts.filter(([v])=> v !== null && v !== 'manual').map(([v])=>v);
  const isManual  = selected != null && !knownVals.includes(selected);
  opts.forEach(([val, label]) => {
    const o = document.createElement('option');
    o.value = val ?? '';
    o.textContent = label;
    if (isManual && val === 'manual') o.selected = true;
    else if (!isManual && ((val === null && selected == null) || val === selected)) o.selected = true;
    sel.appendChild(o);
  });
  _bwManualShow(isManual, isManual ? selected : null);
}
function bwSelectChange(sel) {
  if (sel.value === 'manual') {
    _bwManualShow(true, null);
    document.getElementById('ch-edit-bw-manual').focus();
  } else {
    _bwManualShow(false, null);
  }
}
function openChEditModal(ch) {
  document.getElementById('ch-edit-id').value    = ch.id;
  document.getElementById('ch-edit-name').value  = ch.name;
  document.getElementById('ch-edit-freq').value  = (ch.freq / 1e6).toFixed(4);
  document.getElementById('ch-edit-mode').value  = ch.mode;
  fillBwSelect(ch.mode, ch.bandwidth);
  const gainVal = ch.gain != null ? ch.gain : 20;
  document.getElementById('ch-edit-gain').value = gainVal;
  _chEditGainNull = ch.gain == null;
  document.getElementById('ch-edit-gain-val').textContent = _chEditGainNull ? 'Standard' : '×' + parseFloat(gainVal).toFixed(0);
  const sqVal = ch.squelch != null ? ch.squelch : -60;
  document.getElementById('ch-edit-sq').value = sqVal;
  document.getElementById('ch-edit-sq-val').textContent = sqVal + ' dB';
  document.getElementById('ch-edit-modal-bg').style.display = 'flex';
}
function closeChEditModal() {
  document.getElementById('ch-edit-modal-bg').style.display = 'none';
}
function submitChEdit() {
  const id   = document.getElementById('ch-edit-id').value;
  const name = document.getElementById('ch-edit-name').value.trim();
  const freq = parseFloat(document.getElementById('ch-edit-freq').value);
  const mode = document.getElementById('ch-edit-mode').value;
  const gainV= document.getElementById('ch-edit-gain').value;
  const sqV   = document.getElementById('ch-edit-sq').value;
  const bwSel = document.getElementById('ch-edit-bw').value;
  const bwV   = bwSel === 'manual' ? (document.getElementById('ch-edit-bw-manual').value||'') : bwSel;
  if (!name || isNaN(freq)) { toast('Name und Frequenz sind Pflichtfelder', true); return; }
  const body = {
    name, freq: Math.round(freq * 1e6), mode,
    gain:      _chEditGainNull ? null : parseFloat(gainV),
    squelch:   sqV  !== '' ? parseInt(sqV)      : null,
    bandwidth: bwV  !== '' ? parseInt(bwV)       : null,
  };
  fetch('/banks/channels/' + id + '/update', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  }).then(r => {
    if (r.ok) { closeChEditModal(); refreshBankChannels(); toast('Gespeichert'); }
    else       r.text().then(t => toast(t || 'Fehler', true));
  });
}

function deleteBankChannel(chId) {
  if (!confirm('Kanal aus der Bank löschen?')) return;
  fetch('/banks/channels/' + chId + '/delete', {method:'POST'})
    .then(r => r.ok ? (refreshBankChannels(), toast('Gelöscht')) : toast('Fehler', true));
}

function openSaveModal() {
  const freq = _state.freq || 0;
  document.getElementById('save-freq-display').textContent =
    freq ? (freq/1e6).toFixed(4) + ' MHz  ' + (_state.mode || '') : '–';
  const rawName = _state.channel || '';
  document.getElementById('save-ch-name').value = rawName.split('(')[0].trim();
  const sel = document.getElementById('save-bank-sel');
  sel.innerHTML = '';
  _bankSummary.forEach(b => {
    const opt = document.createElement('option');
    opt.value = b.bank;
    opt.textContent = 'B' + b.bank + ': ' + b.name;
    if (b.bank === _viewBankId) opt.selected = true;
    sel.appendChild(opt);
  });
  document.getElementById('save-modal-bg').style.display = 'flex';
  document.getElementById('save-ch-name').focus();
  document.getElementById('save-ch-name').select();
}

function closeSaveModal() {
  document.getElementById('save-modal-bg').style.display = 'none';
}

function submitSave() {
  const name   = document.getElementById('save-ch-name').value.trim();
  const bankId = parseInt(document.getElementById('save-bank-sel').value);
  if (!name) { toast('Name fehlt', true); return; }
  fetch('/banks/' + bankId + '/save_current', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name})
  }).then(r => {
    if (r.ok) { closeSaveModal(); refreshBankChannels(); toast('In Bank ' + bankId + ' gespeichert'); }
    else r.text().then(t => toast(t, true));
  });
}

function bankRenamePrompt() {
  const b = _bankSummary.find(x => x.bank === _viewBankId);
  const cur = b ? b.name : 'Bank ' + _viewBankId;
  const name = prompt('Name für Bank ' + _viewBankId + ':', cur);
  if (!name || !name.trim()) return;
  fetch('/rename/bank/' + _viewBankId, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name: name.trim()})
  }).then(r => r.ok ? toast('Bank umbenannt') : toast('Fehler', true));
}

function bankTuneChannel(ch) {
  fetch('/tune/freq', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({
      freq: ch.freq, mode: ch.mode, name: ch.name,
      group: ch.group, gain: ch.gain, squelch: ch.squelch, bandwidth: ch.bandwidth
    })
  }).then(r => r.ok ? toast(ch.name + '  ' + (ch.freq/1e6).toFixed(4)+' MHz') : toast('Fehler', true));
}

function exportBanks() {
  window.location.href = '/banks/export';
}

function importBanks(input) {
  const file = input.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = e => {
    let data;
    try { data = JSON.parse(e.target.result); }
    catch { toast('Ungültige JSON-Datei', true); input.value = ''; return; }
    fetch('/banks/import', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(data)
    }).then(r => r.json()).then(d => {
      refreshBankChannels();
      toast(d.imported + ' Kanäle importiert');
    }).catch(() => toast('Import fehlgeschlagen', true));
    input.value = '';
  };
  reader.readAsText(file);
}

refreshBankChannels();

// ── Aktionshelfer ────────────────────────────────────────────────────────────
function cmd(action) { fetch('/cmd/' + action, {method:'POST'}); }

function tuneManual() {
  const mhz = parseFloat(document.getElementById('freq-input').value.replace(',', '.'));
  const mode = document.getElementById('mode-sel').value;
  if (isNaN(mhz) || mhz < 0.1 || mhz > 2000) { toast('Ungültige Frequenz', true); return; }
  fetch('/tune/freq', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({freq: Math.round(mhz * 1e6), mode})
  }).then(r => r.ok ? toast(mhz.toFixed(4) + ' MHz ' + mode) : toast('Fehler', true));
}

function setSq(val) {
  _sqPending = true;
  document.getElementById('sq-val').textContent = val + ' dB';
  clearTimeout(setSq._t);
  setSq._t = setTimeout(() => {
    fetch('/set/squelch', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({level: parseInt(val)})
    }).then(() => { _sqPending = false; });
  }, 200);
}

function setVol(val) {
  val = parseInt(val);
  if (!isNaN(val)) document.getElementById('vol-slider').value = val;
  document.getElementById('vol-val').textContent = val + '%';
  _volPending = true;
  clearTimeout(setVol._t);
  setVol._t = setTimeout(() => {
    fetch('/set/volume', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({volume: val})
    }).then(() => { _volPending = false; });
  }, 150);
}

function setGain(val) {
  val = parseFloat(val);
  document.getElementById('gain-val').textContent = '×' + val.toFixed(0);
  _gainPending = true;
  clearTimeout(setGain._t);
  setGain._t = setTimeout(() => {
    fetch('/set/gain', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({gain: val})
    }).then(() => { _gainPending = false; });
  }, 150);
}

function chEditGainUpdate(val) {
  _chEditGainNull = false;
  document.getElementById('ch-edit-gain-val').textContent = '×' + parseFloat(val).toFixed(0);
}
function chEditGainReset() {
  _chEditGainNull = true;
  document.getElementById('ch-edit-gain').value = 20;
  document.getElementById('ch-edit-gain-val').textContent = 'Standard';
}

function setComp(enabled) {
  const cb = document.getElementById('comp-check');
  cb._changing = true;
  fetch('/set/compressor', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({enabled})
  }).then(() => { cb._changing = false; toast(enabled ? 'Kompressor ein' : 'Kompressor aus'); });
}

function renameActive() {
  const cur = document.getElementById('name-label').textContent;
  const n = prompt('Neuer Name:', cur);
  if (!n || !n.trim()) return;
  fetch('/rename/current', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name: n.trim()})
  }).then(r => r.ok ? toast('Umbenannt') : toast('Fehler', true));
}





// ── WLAN-Hotspot-Einstellungen ────────────────────────────────────────────────
function showWifiSettings() {
  fetch('/hotspot/info').then(r => r.json()).then(d => {
    document.getElementById('wifi-ssid').value = d.ssid || '';
    document.getElementById('wifi-pass').value = '';
    document.getElementById('wifi-modal-bg').style.display = 'flex';
    document.getElementById('wifi-ssid').focus();
  });
}

function closeWifiModal() {
  document.getElementById('wifi-modal-bg').style.display = 'none';
}

function submitWifiSettings() {
  const ssid = document.getElementById('wifi-ssid').value.trim();
  const pass = document.getElementById('wifi-pass').value;
  if (!ssid)        { toast('SSID fehlt', true); return; }
  if (pass.length > 0 && pass.length < 8) { toast('Passwort min. 8 Zeichen', true); return; }
  fetch('/hotspot/change', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ssid, password: pass || null})
  }).then(r => {
    if (r.ok) {
      closeWifiModal();
      toast('WLAN geändert – kurz neu verbinden');
      document.getElementById('hotspot-ssid').textContent = ssid;
    } else {
      r.text().then(t => toast(t, true));
    }
  });
}

document.getElementById('wifi-modal-bg').addEventListener('click', e => {
  if (e.target.id === 'wifi-modal-bg') closeWifiModal();
});

// Hotspot-Status beim Start abrufen
fetch('/hotspot/info').then(r => r.json()).then(d => {
  document.getElementById('hotspot-ssid').textContent = d.ssid || '–';
  const pill = document.getElementById('hotspot-status');
  if (d.active) {
    pill.textContent = 'aktiv';
    pill.style.background = 'var(--act)';
    pill.style.color = '#000';
  } else {
    pill.textContent = 'inaktiv';
    pill.style.background = 'var(--dim)';
    pill.style.color = 'var(--txt)';
  }
}).catch(() => {});

document.getElementById('save-modal-bg').addEventListener('click', e => {
  if (e.target.id === 'save-modal-bg') closeSaveModal();
});
document.getElementById('ch-edit-modal-bg').addEventListener('click', e => {
  if (e.target.id === 'ch-edit-modal-bg') closeChEditModal();
});
document.addEventListener('keydown', e => { if (e.key === 'Escape') { closeSaveModal(); closeChEditModal(); } });

function toast(msg, err=false) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'show' + (err ? ' err' : '');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.className = '', 2500);
}
</script>
</body></html>"""


class WebUI:
    def __init__(self, scanner):
        self._scanner = scanner
        self._clients: list[queue.Queue] = []
        self._lock = threading.Lock()

    def start(self):
        t = threading.Thread(target=self._run_flask, daemon=True, name="web-ui")
        t.start()
        # Broadcast-Queue: Stream-Thread legt Signal ab, dedizierter Thread macht die DB-Abfrage.
        self._bcast_q: queue.Queue = queue.Queue(maxsize=4)
        threading.Thread(target=self._broadcast_loop, daemon=True, name="sse-bcast").start()
        _orig = self._scanner.on_state_change
        def _hook():
            _orig()
            try:
                self._bcast_q.put_nowait(True)
            except queue.Full:
                pass   # doppeltes Update verwerfen
        self._scanner.on_state_change = _hook

    def _broadcast_loop(self):
        while True:
            self._bcast_q.get()      # warten auf Signal
            self._broadcast()        # DB-Abfrage + SSE-Push im eigenen Thread

    def _broadcast(self):
        data = json.dumps(self._scanner.status_dict())
        with self._lock:
            dead = []
            for q in self._clients:
                try:    q.put_nowait(data)
                except queue.Full: dead.append(q)
            for q in dead: self._clients.remove(q)

    def _run_flask(self):
        try:
            from flask import Flask, Response, request, jsonify
        except ImportError:
            log.warning("flask nicht installiert")
            return

        app = Flask(__name__)

        @app.route("/")
        def index():
            return _HTML, 200, {"Content-Type": "text/html; charset=utf-8"}

        @app.route("/events")
        def events():
            q: queue.Queue = queue.Queue(maxsize=20)
            with self._lock: self._clients.append(q)
            def stream():
                try:
                    yield f"data: {json.dumps(self._scanner.status_dict())}\n\n"
                    while True:
                        try:    yield f"data: {q.get(timeout=15)}\n\n"
                        except queue.Empty: yield ": keepalive\n\n"
                finally:
                    with self._lock:
                        try:
                            self._clients.remove(q)
                        except ValueError:
                            pass
            return Response(stream(), mimetype="text/event-stream")

        # ── Abstimmung ────────────────────────────────────────────────────────

        @app.route("/tune/<int:index>", methods=["POST"])
        def tune(index):
            self._scanner.freq.select(index)
            self._scanner._tune_current()
            self._scanner.on_state_change()
            return "", 204

        @app.route("/tune/freq", methods=["POST"])
        def tune_freq():
            """Direkte Frequenzeingabe in Hz + Modus (+ optionale Kanalattribute)."""
            data = request.get_json(silent=True) or {}
            freq = data.get("freq")
            mode = data.get("mode", "NFM")
            if not freq or not isinstance(freq, int) or freq < 100_000 or freq > 2_000_000_000:
                return "Ungültige Frequenz", 400
            if mode not in cfg.MODES:
                return "Unbekannter Modus", 400
            from core.frequency import Channel
            name      = str(data.get("name") or f"{freq/1e6:.4f} MHz").strip()
            group     = str(data.get("group") or "Misc").strip()
            raw_gain  = data.get("gain")
            raw_sq    = data.get("squelch")
            raw_bw    = data.get("bandwidth")
            gain      = float(raw_gain)  if raw_gain  is not None else None
            squelch   = int(raw_sq)      if raw_sq    is not None else None
            bandwidth = int(raw_bw)      if raw_bw    is not None else None
            # Vorherigen Temp-Kanal entfernen damit die Liste nicht wächst
            chs = self._scanner.freq.channels
            while chs and chs[0].is_temp:
                chs.pop(0)
                if self._scanner.freq.index > 0:
                    self._scanner.freq.index -= 1
                if self._scanner.freq.scan_index > 0:
                    self._scanner.freq.scan_index -= 1
            ch = Channel(name=name, freq=freq, mode=mode, group=group,
                         gain=gain, squelch=squelch, bandwidth=bandwidth, is_temp=True)
            chs.insert(0, ch)
            self._scanner.freq.select(0)
            self._scanner._tune_current()
            self._scanner.on_state_change()
            return "", 204

        # ── Audio ─────────────────────────────────────────────────────────────

        @app.route("/set/squelch", methods=["POST"])
        def set_squelch():
            """Squelch-Schwelle direkt setzen (dBFS, −120 bis 0)."""
            data = request.get_json(silent=True) or {}
            level = data.get("level")
            if level is None or not isinstance(level, int) or not -120 <= level <= 0:
                return "Ungültiger Wert", 400
            self._scanner.squelch.level = level
            self._scanner._save_squelch_to_channel()
            # Kein _tune_current() – rtl_fm läuft ohnehin mit -l 0;
            # Python-Squelch reagiert sofort ohne USB-Neustart.
            self._scanner.on_state_change()
            return "", 204

        @app.route("/set/gain", methods=["POST"])
        def set_gain():
            """Software-Gain für den aktiven Kanal setzen (0–100, oder null für Standard)."""
            data = request.get_json(silent=True) or {}
            gain = data.get("gain")
            if gain is not None:
                try:
                    gain = float(gain)
                    if not 0 <= gain <= 100:
                        return "Ungültiger Wert (0–100)", 400
                except (TypeError, ValueError):
                    return "Ungültiger Wert", 400
            self._scanner._save_gain_to_channel(gain)
            self._scanner.on_state_change()
            return "", 204

        @app.route("/set/bandwidth", methods=["POST"])
        def set_bandwidth():
            """Audio-LPF-Bandbreite für den aktiven Kanal setzen (Hz, 200–20000, oder null für Modus-Standard)."""
            data = request.get_json(silent=True) or {}
            bw = data.get("bandwidth")
            if bw is not None:
                if not isinstance(bw, int) or not 200 <= bw <= 20000:
                    return "Ungültiger Wert (200–20000 Hz oder null)", 400
            self._scanner._save_bandwidth_to_channel(bw)
            self._scanner.on_state_change()
            return "", 204

        @app.route("/set/volume", methods=["POST"])
        def set_volume():
            """Lautstärke direkt setzen (0–100)."""
            data = request.get_json(silent=True) or {}
            vol = data.get("volume")
            if vol is None or not isinstance(vol, int) or not 0 <= vol <= 100:
                return "Ungültiger Wert", 400
            self._scanner.audio.set_volume(vol)
            return "", 204

        @app.route("/set/compressor", methods=["POST"])
        def set_compressor():
            data = request.get_json(silent=True) or {}
            enabled = data.get("enabled")
            if not isinstance(enabled, bool):
                return "Ungültiger Wert", 400
            self._scanner.audio.comp_enabled = enabled
            self._scanner.on_state_change()
            return "", 204

        # ── Bänke ─────────────────────────────────────────────────────────────

        @app.route("/bank/load/<int:bank_id>", methods=["POST"])
        def bank_load(bank_id):
            """Bank wählen und ihre Kanäle in den Scanner laden."""
            from core.buttons import ButtonEvent
            self._scanner.banks.set_active_bank(bank_id)
            self._scanner.buttons.inject(ButtonEvent.BANK_LOAD)
            return "", 204

        # ── Bank-API (neue Endpunkte) ──────────────────────────────────────────

        @app.route("/banks")
        def banks_list():
            return jsonify(self._scanner.banks.bank_summary())

        @app.route("/banks/export")
        def banks_export():
            banks_data = []
            for i in range(10):
                name = self._scanner.banks._bank_names[i]
                chs  = self._scanner.banks.list_bank(i)
                banks_data.append({
                    "bank": i, "name": name,
                    "channels": [
                        {"name": ch.name, "freq": ch.freq, "mode": ch.mode,
                         "group": ch.group, "gain": ch.gain,
                         "squelch": ch.squelch, "bandwidth": ch.bandwidth}
                        for ch in chs
                    ],
                })
            payload = json.dumps({"version": 1, "banks": banks_data}, indent=2, ensure_ascii=False)
            return Response(payload, mimetype="application/json",
                            headers={"Content-Disposition":
                                     "attachment; filename=sdr_banks.json"})

        @app.route("/banks/import", methods=["POST"])
        def banks_import():
            data = request.get_json(silent=True) or {}
            if data.get("version") != 1 or "banks" not in data:
                return "Ungültiges Format (version:1 + banks erwartet)", 400
            imported = 0
            for bdata in data["banks"]:
                bank_id   = bdata.get("bank")
                bank_name = str(bdata.get("name", "")).strip()
                if not isinstance(bank_id, int) or not 0 <= bank_id <= 9:
                    continue
                if bank_name:
                    self._scanner.banks.rename_bank(bank_id, bank_name)
                for ch in bdata.get("channels", []):
                    name      = str(ch.get("name",  "")).strip()
                    freq      = ch.get("freq")
                    mode      = ch.get("mode",  "NFM")
                    group     = str(ch.get("group", "Misc")).strip() or "Misc"
                    gain      = ch.get("gain")
                    squelch   = ch.get("squelch")
                    bandwidth = ch.get("bandwidth")
                    if not name or not isinstance(freq, int) or mode not in cfg.MODES:
                        continue
                    self._scanner.banks.save(
                        name, freq, mode, group, bank=bank_id,
                        gain=float(gain) if gain is not None else None,
                        squelch=int(squelch) if squelch is not None else None,
                        bandwidth=int(bandwidth) if bandwidth is not None else None)
                    imported += 1
            self._scanner.on_state_change()
            return jsonify({"imported": imported})

        @app.route("/banks/<int:bank_id>/channels")
        def bank_channels_list(bank_id):
            chs = self._scanner.banks.list_bank(bank_id)
            return jsonify([{
                "id": ch.id, "slot": ch.slot, "name": ch.name,
                "freq": ch.freq, "mode": ch.mode, "group": ch.group,
                "gain": ch.gain, "squelch": ch.squelch, "bandwidth": ch.bandwidth,
            } for ch in chs])

        @app.route("/banks/<int:bank_id>/save_current", methods=["POST"])
        def bank_save_current(bank_id):
            """Aktuellen Scanner-Kanal direkt in eine bestimmte Bank speichern."""
            ch = self._scanner.freq.current
            if not ch:
                return "Kein aktiver Kanal", 400
            data = request.get_json(silent=True) or {}
            name = str(data.get("name", "")).strip() or ch.name
            self._scanner.banks.save(
                name, ch.freq, ch.mode, ch.group, bank=bank_id,
                gain=ch.gain, squelch=ch.squelch, bandwidth=ch.bandwidth)
            self._scanner.on_state_change()
            return "", 204

        @app.route("/banks/channels/<int:ch_id>/delete", methods=["POST"])
        def bank_channel_delete(ch_id):
            all_chs = self._scanner.banks.all_channels()
            target = next((c for c in all_chs if c.id == ch_id), None)
            if not target:
                return "Nicht gefunden", 404
            self._scanner.banks.delete(target.bank, target.slot)
            return "", 204

        @app.route("/banks/channels/<int:ch_id>/update", methods=["POST"])
        def bank_channel_update(ch_id):
            data  = request.get_json(silent=True) or {}
            name  = str(data.get("name", "")).strip()
            freq  = data.get("freq")
            mode  = data.get("mode", "NFM")
            gain      = data.get("gain")
            squelch   = data.get("squelch")
            bandwidth = data.get("bandwidth")
            if not name:
                return "Name darf nicht leer sein", 400
            if not isinstance(freq, int) or freq < 100_000 or freq > 2_000_000_000:
                return "Ungültige Frequenz", 400
            if mode not in cfg.MODES:
                return "Unbekannter Modus", 400
            all_chs = self._scanner.banks.all_channels()
            target  = next((c for c in all_chs if c.id == ch_id), None)
            if not target:
                return "Nicht gefunden", 404
            with self._scanner.banks._lock:
                self._scanner.banks._conn.execute(
                    "UPDATE memory_banks SET name=?, freq=?, mode=?, gain=?, squelch=?, bandwidth=? WHERE id=?",
                    (name, freq, mode,
                     float(gain) if gain is not None else None,
                     int(squelch) if squelch is not None else None,
                     int(bandwidth) if bandwidth is not None else None,
                     ch_id),
                )
                self._scanner.banks._conn.commit()
            # RAM-Kanal und aktiven Squelch synchronisieren
            sq_int = int(squelch) if squelch is not None else None
            bw_int = int(bandwidth) if bandwidth is not None else None
            for ch in self._scanner.freq.channels:
                if ch.freq == target.freq and ch.mode == target.mode:
                    ch.name      = name
                    ch.squelch   = sq_int
                    ch.bandwidth = bw_int
            cur = self._scanner.freq.current
            if cur and cur.freq == target.freq and cur.mode == target.mode:
                if sq_int is not None:
                    self._scanner.squelch.level = sq_int
                bw = bw_int if bw_int is not None else cfg.MODE_BANDWIDTH.get(mode)
                lpf = None if mode == "WFM" else (bw // 3 if bw else cfg.MODE_AUDIO_LPF.get(mode))
                self._scanner.audio.set_lpf(lpf)
            self._scanner.on_state_change()
            return "", 204

        @app.route("/banks/channels/<int:ch_id>/rename", methods=["POST"])
        def bank_channel_rename(ch_id):
            data = request.get_json(silent=True) or {}
            name = str(data.get("name", "")).strip()
            if not name:
                return "Name leer", 400
            if not self._scanner.banks.rename_channel_by_id(ch_id, name):
                return "Nicht gefunden", 404
            return "", 204

        @app.route("/rename/bank/<int:bank_id>", methods=["POST"])
        def rename_bank(bank_id):
            data = request.get_json(silent=True) or {}
            name = str(data.get("name", "")).strip()
            if not name: return "Name leer", 400
            self._scanner.banks.rename_bank(bank_id, name)
            return "", 204

        # ── Kanal umbenennen ─────────────────────────────────────────────────

        @app.route("/rename/current", methods=["POST"])
        def rename_current():
            data = request.get_json(silent=True) or {}
            name = str(data.get("name", "")).strip()
            if not name: return "Name leer", 400
            from core.buttons import ButtonEvent
            self._scanner.buttons.inject(ButtonEvent.RENAME, {"name": name})
            return "", 204

        # ── Hotspot ───────────────────────────────────────────────────────────

        @app.route("/hotspot/info")
        def hotspot_info():
            """Liest aktuelle SSID und Hotspot-Status aus hostapd.conf."""
            import subprocess, os
            conf = "/etc/hostapd/hostapd.conf"
            ssid = "SDR-Scanner"
            active = False
            if os.path.exists(conf):
                with open(conf) as f:
                    for line in f:
                        if line.startswith("ssid="):
                            ssid = line.split("=", 1)[1].strip()
            try:
                result = subprocess.run(
                    ["systemctl", "is-active", "hostapd"],
                    capture_output=True, text=True, timeout=3
                )
                active = result.stdout.strip() == "active"
            except Exception:
                pass
            return jsonify({"ssid": ssid, "active": active})

        @app.route("/hotspot/change", methods=["POST"])
        def hotspot_change():
            """Ändert SSID und/oder Passwort und startet hostapd neu."""
            import subprocess, os
            data = request.get_json(silent=True) or {}
            ssid     = str(data.get("ssid", "")).strip()
            password = data.get("password")  # None = nicht ändern

            if not ssid or len(ssid) > 32:
                return "Ungültige SSID", 400
            if password is not None and len(str(password)) < 8:
                return "Passwort min. 8 Zeichen", 400

            conf = "/etc/hostapd/hostapd.conf"
            if not os.path.exists(conf):
                return "hostapd nicht eingerichtet", 503

            # Konfigurationsdatei aktualisieren
            try:
                with open(conf) as f:
                    lines = f.readlines()
                new_lines = []
                for line in lines:
                    if line.startswith("ssid="):
                        new_lines.append(f"ssid={ssid}\n")
                    elif line.startswith("wpa_passphrase=") and password:
                        new_lines.append(f"wpa_passphrase={password}\n")
                    else:
                        new_lines.append(line)
                with open(conf, "w") as f:
                    f.writelines(new_lines)
            except PermissionError:
                return "Keine Schreibrechte auf hostapd.conf – als root starten?", 403

            # hostapd neu starten
            try:
                subprocess.run(["systemctl", "restart", "hostapd"],
                               timeout=10, check=True)
            except subprocess.CalledProcessError:
                return "hostapd-Neustart fehlgeschlagen", 500
            except FileNotFoundError:
                return "systemctl nicht verfügbar (nur auf Pi)", 501

            log.info("Hotspot geändert: SSID=%s", ssid)
            return "", 204

        # ── Scanner-Befehle ───────────────────────────────────────────────────

        @app.route("/cmd/<action>", methods=["POST"])
        def command(action):
            from core.buttons import ButtonEvent
            try:
                self._scanner.buttons.inject(ButtonEvent[action])
                return "", 204
            except KeyError:
                return "Unbekannte Aktion", 400

        log.info("Web-UI auf http://0.0.0.0:%d", cfg.WEB_PORT)
        app.run(host=cfg.WEB_HOST, port=cfg.WEB_PORT,
                debug=False, use_reloader=False, threaded=True)
