<template>
  <div>
    <h3>历史实验</h3>
    <el-table :data="experiments" v-loading="loading" stripe>
      <el-table-column prop="created_at" label="创建时间" width="180" />
      <el-table-column prop="model_id" label="模型" width="220">
        <template #default="{ row }">{{ modelName(row.model_id) }}</template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="120">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)">{{ statusText(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="log_count" label="日志行数" width="100" />
      <el-table-column label="操作">
        <template #default="{ row }">
          <el-button
            size="small"
            type="primary"
            link
            :disabled="row.status !== 'done' && row.status !== 'failed'"
            @click="$router.push(`/report/${row.exp_id}`)"
          >
            查看报告
          </el-button>
          <el-button
            size="small"
            link
            :disabled="row.status === 'done' || row.status === 'failed'"
            @click="$router.push(`/running/${row.exp_id}`)"
          >
            运行详情
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-if="!loading && experiments.length === 0" description="还没有实验记录，去创建第一个实验吧" />
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { fetchExperiments, fetchModels, type ExperimentInfo, type ModelInfo } from '../api'

const experiments = ref<ExperimentInfo[]>([])
const models = ref<ModelInfo[]>([])
const loading = ref(true)

function modelName(id: string): string {
  return models.value.find((m) => m.id === id)?.name ?? id
}

function statusType(s: string): 'success' | 'warning' | 'danger' | 'info' {
  if (s === 'done') return 'success'
  if (s === 'failed') return 'danger'
  if (s === 'running') return 'warning'
  return 'info'
}

function statusText(s: string): string {
  const map: Record<string, string> = {
    pending: '排队中',
    running: '运行中',
    done: '已完成',
    failed: '失败'
  }
  return map[s] ?? s
}

onMounted(async () => {
  try {
    const [exps, ms] = await Promise.all([fetchExperiments(), fetchModels()])
    experiments.value = exps
    models.value = ms
  } finally {
    loading.value = false
  }
})
</script>
