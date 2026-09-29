<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  fetchDataFields,
  fetchJobStatus,
  fetchOverview,
  searchStocks,
  startFetchJob,
  wsDataUrl,
  type FieldInfo,
  type FetchJobStatus,
  type OverviewData,
  type StockBrief
} from '../api'

// ---------------- 已存数据概览 ----------------
const overview = ref<OverviewData | null>(null)
const loadingOverview = ref(false)

async function refreshOverview() {
  loadingOverview.value = true
  try {
    overview.value = await fetchOverview()
  } catch (e) {
    alert(`读取数据概览失败: ${(e as Error).message}`)
  } finally {
    loadingOverview.value = false
  }
}

// ---------------- 股票选择 ----------------
const stockInput = ref('')
const searchKeyword = ref('')
const searchResults = ref<StockBrief[]>([])
const searching = ref(false)
const selectedStocks = ref<string[]>([])

const PRESET_POOLS: { label: string; codes: string[] }[] = [
  { label: '浦发银行 sh600000', codes: ['SH600000'] },
  { label: '平安银行 sz000001', codes: ['SZ000001'] },
  { label: '贵州茅台 sh600519', codes: ['SH600519'] },
  { label: '招商银行 sh600036', codes: ['SH600036'] }
]

let searchTimer: number | undefined
function onSearchInput() {
  window.clearTimeout(searchTimer)
  if (!searchKeyword.value.trim()) {
    searchResults.value = []
    return
  }
  searchTimer = window.setTimeout(async () => {
    searching.value = true
    try {
      const res = await searchStocks(searchKeyword.value)
      searchResults.value = res.results
    } catch {
      searchResults.value = []
    } finally {
      searching.value = false
    }
  }, 400)
}

function addStock(code: string) {
  const c = code.trim().toUpperCase()
  if (!c) return
  if (!/^(SH|SZ)\d{6}$/.test(c)) {
    alert('代码格式应为 sh600000 / sz000001')
    return
  }
  if (!selectedStocks.value.includes(c)) selectedStocks.value.push(c)
  stockInput.value = ''
}

function removeStock(code: string) {
  selectedStocks.value = selectedStocks.value.filter((c) => c !== code)
}

function addPreset(codes: string[]) {
  codes.forEach((c) => addStock(c))
}

// ---------------- 日期与字段 ----------------
const startDate = ref('2020-01-01')
const endDate = ref('2020-09-25')
const allFields = ref<FieldInfo[]>([])
const selectedFields = ref<string[]>([])

onMounted(async () => {
  refreshOverview()
  try {
    const res = await fetchDataFields()
    allFields.value = res.fields
    selectedFields.value = res.fields.map((f) => f.key)
  } catch {
    /* 字段加载失败时允许手动输入 */
  }
})

function toggleField(key: string) {
  selectedFields.value = selectedFields.value.includes(key)
    ? selectedFields.value.filter((k) => k !== key)
    : [...selectedFields.value, key]
}

// ---------------- 拉取任务 ----------------
const jobId = ref('')
const jobStatus = ref<FetchJobStatus | null>(null)
const jobLogs = ref<string[]>([])
const submitting = ref(false)
let pollTimer: number | undefined
let ws: WebSocket | undefined

const logBox = ref<HTMLElement | null>(null)

async function submitJob() {
  if (!selectedStocks.value.length) {
    alert('请先选择至少一只股票')
    return
  }
  if (!selectedFields.value.length) {
    alert('请至少选择一个字段')
    return
  }
  submitting.value = true
  jobLogs.value = []
  try {
    const res = await startFetchJob({
      stocks: selectedStocks.value,
      start_date: startDate.value,
      end_date: endDate.value,
      fields: selectedFields.value
    })
    jobId.value = res.job_id
    connectWs(res.job_id)
    pollTimer = window.setInterval(async () => {
      try {
        jobStatus.value = await fetchJobStatus(res.job_id)
        if (jobStatus.value.status === 'done' || jobStatus.value.status === 'failed') {
          window.clearInterval(pollTimer)
          refreshOverview()
        }
      } catch {
        /* 轮询失败下次再试 */
      }
    }, 2000)
  } catch (e) {
    alert(`创建拉取任务失败: ${(e as Error).message}`)
  } finally {
    submitting.value = false
  }
}

function connectWs(id: string) {
  ws?.close()
  ws = new WebSocket(wsDataUrl(id))
  ws.onmessage = (ev) => {
    jobLogs.value.push(ev.data)
    // 自动滚动到底部
    requestAnimationFrame(() => {
      logBox.value?.scrollTo({ top: logBox.value.scrollHeight })
    })
  }
}

onBeforeUnmount(() => {
  window.clearInterval(pollTimer)
  ws?.close()
})

const progressPct = computed(() => {
  const s = jobStatus.value
  if (!s || !s.total) return 0
  return Math.round((s.finished / s.total) * 100)
})
</script>

<template>
  <div class="page">
    <section class="card">
      <h2>数据管理 <span class="sub">按需拉取 A 股行情到 qlib 数据集（cn_data_full）</span></h2>

      <!-- 已存数据概览 -->
      <div class="overview">
        <div class="ov-item">
          <b>交易日历</b>
          <span v-if="overview?.calendar_start">
            {{ overview.calendar_start }} ~ {{ overview.calendar_end }}（{{ overview.trading_days }} 个交易日）
          </span>
          <span v-else class="muted">暂无</span>
        </div>
        <div class="ov-item">
          <b>已存股票</b>
          <span>{{ overview?.stock_count ?? 0 }} 只</span>
        </div>
        <div class="ov-item">
          <b>已有字段</b>
          <span>{{ overview?.fields.join('、') || '暂无' }}</span>
        </div>
      </div>

      <details v-if="overview?.stocks?.length" class="stock-detail">
        <summary>查看已存股票明细（{{ overview.stocks.length }} 只）</summary>
        <table>
          <thead>
            <tr><th>代码</th><th>覆盖区间</th></tr>
          </thead>
          <tbody>
            <tr v-for="s in overview.stocks" :key="s.code">
              <td>{{ s.code }}</td>
              <td>{{ s.start }} ~ {{ s.end }}</td>
            </tr>
          </tbody>
        </table>
      </details>
    </section>

    <section class="card">
      <h3>① 选择股票</h3>
      <div class="row">
        <input
          v-model="stockInput"
          placeholder="输入代码后回车，如 sh600000"
          @keydown.enter="addStock(stockInput)"
        />
        <button class="btn" @click="addStock(stockInput)">添加</button>
      </div>
      <div class="row">
        <input v-model="searchKeyword" placeholder="或按名称/代码搜索，如 浦发" @input="onSearchInput" />
        <span v-if="searching" class="muted">搜索中…</span>
      </div>
      <div v-if="searchResults.length" class="search-list">
        <button v-for="r in searchResults" :key="r.code" class="chip" @click="addStock(r.code)">
          {{ r.code }} {{ r.name }}
        </button>
      </div>
      <div class="presets">
        <span class="muted">快捷添加：</span>
        <button v-for="p in PRESET_POOLS" :key="p.label" class="chip" @click="addPreset(p.codes)">
          {{ p.label }}
        </button>
      </div>
      <div v-if="selectedStocks.length" class="selected">
        <span v-for="c in selectedStocks" :key="c" class="chip selected-chip" @click="removeStock(c)">
          {{ c }} ✕
        </span>
      </div>
    </section>

    <section class="card">
      <h3>② 时间区间</h3>
      <div class="row">
        <label>开始 <input v-model="startDate" type="date" /></label>
        <label>结束 <input v-model="endDate" type="date" /></label>
      </div>
      <p class="tip">提示：区间超出已有日历时会自动同步 baostock 交易日历；数据合并时同日期以新数据为准。</p>
    </section>

    <section class="card">
      <h3>③ 选择字段</h3>
      <div class="fields">
        <label v-for="f in allFields" :key="f.key" class="field-check">
          <input
            type="checkbox"
            :checked="selectedFields.includes(f.key)"
            @change="toggleField(f.key)"
          />
          {{ f.label }}（{{ f.key }}）
        </label>
      </div>
    </section>

    <section class="card">
      <h3>④ 执行</h3>
      <button class="btn primary" :disabled="submitting || jobStatus?.status === 'running'" @click="submitJob">
        {{ jobStatus?.status === 'running' ? '拉取中…' : '开始拉取' }}
      </button>

      <div v-if="jobStatus" class="progress-wrap">
        <div class="progress-bar">
          <div class="progress-fill" :style="{ width: progressPct + '%' }"></div>
        </div>
        <span>{{ jobStatus.finished }} / {{ jobStatus.total }}（成功 {{ jobStatus.ok }}<template v-if="jobStatus.failed.length">，失败 {{ jobStatus.failed.length }}</template>）</span>
      </div>

      <div v-if="jobLogs.length" ref="logBox" class="log-box">
        <div v-for="(l, i) in jobLogs" :key="i" class="log-line">{{ l }}</div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 16px; }
.card { background: #fff; border-radius: 10px; padding: 16px 20px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }
h2 { margin: 0 0 12px; font-size: 18px; }
h3 { margin: 0 0 10px; font-size: 15px; color: #334; }
.sub { font-size: 12px; color: #888; font-weight: normal; margin-left: 8px; }
.overview { display: flex; gap: 24px; flex-wrap: wrap; padding: 10px 12px; background: #f6f8fa; border-radius: 8px; }
.ov-item { display: flex; flex-direction: column; gap: 2px; font-size: 13px; }
.ov-item b { color: #445; font-size: 12px; }
.muted { color: #999; font-size: 13px; }
.stock-detail { margin-top: 10px; }
.stock-detail table { width: 100%; font-size: 12px; border-collapse: collapse; margin-top: 8px; }
.stock-detail th, .stock-detail td { border-bottom: 1px solid #eee; padding: 4px 8px; text-align: left; }
.row { display: flex; gap: 8px; align-items: center; margin-bottom: 10px; flex-wrap: wrap; }
input { padding: 6px 10px; border: 1px solid #ccd; border-radius: 6px; font-size: 13px; }
input[type='date'] { padding: 5px; }
.btn { padding: 7px 16px; border: none; border-radius: 6px; background: #e8ecf3; cursor: pointer; font-size: 13px; }
.btn.primary { background: #2f6fed; color: #fff; padding: 9px 26px; font-size: 14px; }
.btn:disabled { opacity: .5; cursor: not-allowed; }
.chip { padding: 4px 10px; border-radius: 14px; border: 1px solid #ccd; background: #f8fafc; font-size: 12px; cursor: pointer; margin: 2px 4px 2px 0; }
.selected-chip { background: #2f6fed; color: #fff; border-color: #2f6fed; }
.search-list, .presets, .selected { margin: 6px 0; }
.fields { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 6px; }
.field-check { font-size: 13px; display: flex; align-items: center; gap: 6px; }
.tip { font-size: 12px; color: #8a94a6; margin: 4px 0 0; }
.progress-wrap { display: flex; align-items: center; gap: 12px; margin-top: 12px; font-size: 13px; }
.progress-bar { flex: 1; height: 8px; background: #e8ecf3; border-radius: 4px; overflow: hidden; }
.progress-fill { height: 100%; background: #2f6fed; transition: width .3s; }
.log-box { margin-top: 12px; max-height: 260px; overflow-y: auto; background: #0d1117; color: #c9d1d9; border-radius: 8px; padding: 10px 12px; font-family: Consolas, monospace; font-size: 12px; }
.log-line { white-space: pre-wrap; line-height: 1.6; }
</style>
