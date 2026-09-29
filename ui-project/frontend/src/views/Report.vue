<template>
  <div>
    <h3>实验报告 —— {{ expId }}</h3>

    <el-alert v-if="loadError" type="warning" show-icon :closable="false">
      <template #title>{{ loadError }}</template>
    </el-alert>

    <!-- 指标卡 -->
    <el-row :gutter="16" class="metric-row">
      <el-col v-for="m in metricCards" :key="m.key" :xs="12" :sm="12" :md="6">
        <el-card shadow="hover" class="metric-card">
          <el-tooltip :content="m.tip" placement="top">
            <div class="metric-label">
              {{ m.label }}
              <el-icon class="tip-icon"><QuestionFilled /></el-icon>
            </div>
          </el-tooltip>
          <div class="metric-value" :class="m.value < 0 ? 'negative' : 'positive'">
            {{ formatMetric(m.value) }}
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-alert
      v-if="status !== 'done'"
      type="info"
      show-icon
      :closable="false"
      title="实验尚未完成，指标仅供参考（可能为空）。完成后刷新本页。"
      style="margin-bottom: 16px"
    />

    <!-- 收益曲线 -->
    <el-card shadow="never" class="chart-card">
      <template #header>累计收益曲线</template>
      <div v-show="hasChart" ref="chartEl" class="chart" />
      <el-empty v-show="!hasChart" description="该实验暂无曲线数据（曲线由 qlib 回测记录生成，正在读取中或该版本未产出）" />
    </el-card>

    <div class="footer-actions">
      <el-button type="primary" @click="$router.push('/')">再跑一个实验</el-button>
      <el-button @click="$router.push('/history')">查看历史实验</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import * as echarts from 'echarts'
import { QuestionFilled } from '@element-plus/icons-vue'
import { fetchReport, type ReportData } from '../api'

const route = useRoute()
const expId = route.params.id as string

const report = ref<ReportData | null>(null)
const loadError = ref('')
const chartEl = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null

const status = computed(() => report.value?.status ?? '')
const hasChart = ref(false)

const METRIC_DEFS = [
  { key: 'ic', label: 'IC', tip: '预测值与真实涨跌的相关系数，>0.03 即具备预测能力，越大越好' },
  { key: 'annualized_return', label: '年化收益', tip: '按回测区间折算的年化收益率，扣除交易成本' },
  { key: 'information_ratio', label: '信息比率', tip: '超额收益与波动之比，衡量风险调整后收益，>1 即优秀' },
  { key: 'max_drawdown', label: '最大回撤', tip: '净值从最高点到最低点的最大跌幅，绝对值越小越好' }
]

const metricCards = computed(() =>
  METRIC_DEFS.map((def) => ({
    ...def,
    value: report.value?.metrics?.[def.key] ?? 0
  }))
)

function formatMetric(v: number): string {
  if (!v) return '--'
  if (Math.abs(v) < 1) return v.toFixed(4)
  return (v * 100).toFixed(2) + '%'
}

function renderChart() {
  // 从 raw 指标中提取曲线型数据（qlib 会输出 series 类型的记录）
  if (!chartEl.value) return
  chart = echarts.init(chartEl.value)
  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['累计收益'] },
    xAxis: { type: 'category' },
    yAxis: { type: 'value', axisLabel: { formatter: (v: number) => (v * 100).toFixed(0) + '%' } },
    series: [{ name: '累计收益', type: 'line', showSymbol: false, data: [] }]
  })
  hasChart.value = true
}

onMounted(async () => {
  try {
    report.value = await fetchReport(expId)
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : String(e)
  }
  renderChart()
  // 未完成时定时刷新指标
  if (status.value !== 'done') {
    const timer = setInterval(async () => {
      try {
        report.value = await fetchReport(expId)
        if (status.value === 'done') clearInterval(timer)
      } catch {
        /* 忽略 */
      }
    }, 10000)
  }
})

onBeforeUnmount(() => {
  chart?.dispose()
})
</script>

<style scoped>
.metric-row {
  margin-bottom: 20px;
}
.metric-card {
  text-align: center;
  margin-bottom: 12px;
}
.metric-label {
  font-size: 13px;
  color: #909399;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  cursor: help;
}
.tip-icon {
  color: #c0c4cc;
}
.metric-value {
  font-size: 26px;
  font-weight: 700;
  margin-top: 6px;
}
.positive {
  color: #f56c6c; /* A 股习惯：涨红 */
}
.negative {
  color: #67c23a;
}
.chart-card {
  margin-bottom: 20px;
}
.chart {
  height: 380px;
  width: 100%;
}
.footer-actions {
  margin-top: 8px;
}
</style>
