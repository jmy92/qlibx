<template>
  <div>
    <h3>实验 {{ expId }}</h3>

    <!-- 阶段步骤条 -->
    <el-steps :active="stageActive" align-center class="steps" :process-status="failed ? 'error' : 'process'">
      <el-step title="启动" description="初始化引擎" />
      <el-step title="模型训练" description="训练预测模型" />
      <el-step title="回测评估" description="模拟交易并计算指标" />
      <el-step :title="failed ? '失败' : '完成'" :description="failed ? '查看日志定位问题' : '生成报告'" />
    </el-steps>

    <!-- 完成后引导 -->
    <el-alert
      v-if="done"
      type="success"
      show-icon
      :closable="false"
      class="done-alert"
    >
      <template #title>
        实验已完成！
        <el-button type="primary" size="small" style="margin-left: 12px" @click="$router.push(`/report/${expId}`)">
          查看报告
        </el-button>
      </template>
    </el-alert>
    <el-alert v-if="failed" type="error" show-icon :closable="false" class="done-alert">
      <template #title>实验失败，请在下方日志中定位错误原因（常见原因：数据未下载、日期区间超出数据范围）</template>
    </el-alert>

    <!-- 日志区 -->
    <div class="log-toolbar">
      <el-switch v-model="autoScroll" active-text="自动跟随" />
      <el-button size="small" @click="copyLogs">复制日志</el-button>
    </div>
    <div ref="logBox" class="log-box"><pre>{{ logs }}</pre></div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { fetchLogs, wsLogsUrl } from '../api'

const route = useRoute()
const expId = route.params.id as string

const logs = ref('')
const autoScroll = ref(true)
const done = ref(false)
const failed = ref(false)
const logBox = ref<HTMLElement | null>(null)

let ws: WebSocket | null = null
let pollTimer: number | null = null

const stageActive = computed(() => {
  if (done.value) return 4
  if (failed.value) return 3
  if (logs.value.includes('backtest') || logs.value.includes('PortAnaRecord')) return 2
  if (logs.value.includes('train') || logs.value.includes('running')) return 1
  return 0
})

function append(line: string) {
  logs.value += line + '\n'
  if (autoScroll.value) {
    nextTick(() => logBox.value?.scrollTo({ top: logBox.value.scrollHeight }))
  }
}

function copyLogs() {
  navigator.clipboard.writeText(logs.value).then(
    () => ElMessage.success('日志已复制'),
    () => ElMessage.error('复制失败')
  )
}

function startPolling() {
  // WebSocket 断开时的降级方案：每 3 秒轮询全量日志
  if (pollTimer !== null) return
  pollTimer = window.setInterval(async () => {
    try {
      const r = await fetchLogs(expId)
      logs.value = r.logs
      if (r.status === 'done') done.value = true
      if (r.status === 'failed') failed.value = true
    } catch {
      /* 忽略轮询错误，等服务恢复 */
    }
  }, 3000)
}

function stopPolling() {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function connect() {
  ws = new WebSocket(wsLogsUrl(expId))
  ws.onmessage = (ev) => {
    const line = ev.data as string
    append(line)
    if (line.includes('实验完成')) done.value = true
    if (line.includes('实验失败')) failed.value = true
  }
  ws.onclose = () => {
    if (!done.value && !failed.value) {
      startPolling() // 断线降级为轮询
    }
  }
  ws.onerror = () => ws?.close()
}

onMounted(async () => {
  // 先拉一次历史日志（进程可能早已启动）
  try {
    const r = await fetchLogs(expId)
    logs.value = r.logs
    if (r.status === 'done') done.value = true
    if (r.status === 'failed') failed.value = true
    if (!done.value && !failed.value) connect()
  } catch {
    ElMessage.error('无法获取实验状态')
    startPolling()
  }
})

onBeforeUnmount(() => {
  ws?.close()
  stopPolling()
})
</script>

<style scoped>
.steps {
  margin: 16px 0 24px;
}
.done-alert {
  margin-bottom: 16px;
}
.log-toolbar {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 8px;
}
.log-box {
  background: #0d1117;
  color: #7ee787;
  border-radius: 8px;
  padding: 16px;
  height: 480px;
  overflow-y: auto;
}
.log-box pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
  font-family: Consolas, 'Courier New', monospace;
  font-size: 12.5px;
  line-height: 1.6;
}
</style>
