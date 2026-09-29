<template>
  <div>
    <!-- 数据就绪提示 -->
    <el-alert
      v-if="dataStatus && !dataStatus.ready"
      type="warning"
      show-icon
      :closable="false"
      class="data-alert"
    >
      <template #title>
        量化数据尚未下载，无法运行实验。请先点击右侧按钮下载 A 股示例数据（约 200MB）。
        <el-button
          size="small"
          type="warning"
          :loading="dataStatus.downloading"
          style="margin-left: 12px"
          @click="onDownloadData"
        >
          {{ dataStatus.downloading ? '下载中…' : '一键下载数据' }}
        </el-button>
      </template>
    </el-alert>

    <!-- 三步引导条 -->
    <el-steps :active="stepActive" align-center class="steps" finish-status="success">
      <el-step title="选择模型" description="点击下方卡片选择一个模型" />
      <el-step title="配置参数" description="设置日期区间与回测参数" />
      <el-step title="运行并查看结果" description="实时观察训练进度与报告" />
    </el-steps>

    <!-- 第一步：模型卡片墙 -->
    <h3 class="section-title">① 选择模型</h3>
    <div v-if="loadingModels" class="loading-box">
      <el-skeleton :rows="3" animated />
    </div>
    <template v-else>
      <div v-for="(models, group) in groupedModels" :key="group" class="group-block">
        <el-tag effect="plain" size="large" class="group-tag">{{ group }}</el-tag>
        <el-row :gutter="16">
          <el-col v-for="m in models" :key="m.id" :xs="24" :sm="12" :md="8" :lg="6">
            <el-card
              shadow="hover"
              class="model-card"
              :class="{ selected: selectedModel?.id === m.id }"
              @click="selectModel(m)"
            >
              <div class="card-head">
                <span class="model-name">{{ m.name }}</span>
                <el-tooltip v-if="m.requires_gpu" content="该模型基于 PyTorch，有 GPU 可加速训练，纯 CPU 也能运行" placement="top">
                  <el-tag type="warning" size="small">建议 GPU</el-tag>
                </el-tooltip>
                <el-tag v-else type="success" size="small">纯 CPU</el-tag>
              </div>
              <div class="model-desc">{{ m.description }}</div>
            </el-card>
          </el-col>
        </el-row>
      </div>
    </template>

    <!-- 第二步：参数表单 -->
    <template v-if="selectedModel">
      <h3 class="section-title">② 配置参数 —— {{ selectedModel.name }}</h3>
      <el-card class="param-card">
        <el-form label-width="120px" label-position="left">
          <el-form-item
            v-for="(spec, key) in selectedModel.params_schema"
            :key="key"
            :label="spec.label"
          >
            <div class="param-row">
              <el-date-picker
                v-if="spec.type === 'date'"
                v-model="formValues[key]"
                type="date"
                value-format="YYYY-MM-DD"
                placeholder="选择日期"
                style="width: 200px"
              />
              <el-select
                v-else-if="spec.type === 'select'"
                v-model="formValues[key]"
                style="width: 200px"
              >
                <el-option
                  v-for="opt in spec.options"
                  :key="opt"
                  :label="opt === 'csi300' ? '沪深300 (csi300)' : '中证500 (csi500)'"
                  :value="opt"
                />
              </el-select>
              <el-input-number
                v-else
                v-model="formValues[key] as number"
                :step="key === 'account' ? 10000000 : 1"
                :min="1"
                style="width: 220px"
              />
              <el-tooltip :content="spec.tip" placement="right">
                <el-icon class="tip-icon"><QuestionFilled /></el-icon>
              </el-tooltip>
            </div>
          </el-form-item>
        </el-form>

        <!-- 第三步：提交 -->
        <h3 class="section-title">③ 开始实验</h3>
        <el-button type="primary" size="large" :disabled="!dataReady" @click="confirmVisible = true">
          开始实验
        </el-button>
        <span v-if="!dataReady" class="no-data-tip">（数据未就绪，请先下载数据）</span>
      </el-card>
    </template>

    <!-- 参数确认弹窗 -->
    <el-dialog v-model="confirmVisible" title="确认实验参数" width="480px">
      <el-descriptions :column="1" border>
        <el-descriptions-item label="模型">{{ selectedModel?.name }}</el-descriptions-item>
        <el-descriptions-item v-for="(v, k) in formValues" :key="k" :label="paramLabel(k as string)">
          {{ v }}
        </el-descriptions-item>
      </el-descriptions>
      <template #footer>
        <el-button @click="confirmVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">确认并运行</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { QuestionFilled } from '@element-plus/icons-vue'
import {
  fetchModels,
  fetchDataStatus,
  downloadData,
  createExperiment,
  type ModelInfo
} from '../api'

const router = useRouter()
const models = ref<ModelInfo[]>([])
const loadingModels = ref(true)
const selectedModel = ref<ModelInfo | null>(null)
const dataStatus = ref<{ ready: boolean; downloading: boolean } | null>(null)
const confirmVisible = ref(false)
const submitting = ref(false)
const formValues = reactive<Record<string, string | number>>({})

const groupedModels = computed(() => {
  const groups: Record<string, ModelInfo[]> = {}
  for (const m of models.value) {
    ;(groups[m.group] ||= []).push(m)
  }
  return groups
})

const stepActive = computed(() => {
  if (!selectedModel.value) return 0
  return Object.keys(formValues).length > 0 ? 2 : 1
})

const dataReady = computed(() => dataStatus.value?.ready ?? false)

function selectModel(m: ModelInfo) {
  selectedModel.value = m
  // 用 schema 默认值填充表单
  Object.keys(formValues).forEach((k) => delete formValues[k])
  for (const [key, spec] of Object.entries(m.params_schema || {})) {
    formValues[key] = spec.default
  }
}

function paramLabel(key: string): string {
  return selectedModel.value?.params_schema?.[key]?.label ?? key
}

async function refreshDataStatus() {
  dataStatus.value = await fetchDataStatus()
}

async function onDownloadData() {
  try {
    const r = await downloadData()
    ElMessage.info(r.message || '下载已启动')
    // 轮询状态
    const timer = setInterval(async () => {
      await refreshDataStatus()
      if (dataStatus.value?.ready || !dataStatus.value?.downloading) clearInterval(timer)
    }, 10000)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
  }
}

async function submit() {
  if (!selectedModel.value) return
  submitting.value = true
  try {
    const r = await createExperiment({
      model_id: selectedModel.value.id,
      params: { ...formValues }
    })
    ElMessage.success('实验已提交')
    confirmVisible.value = false
    router.push(`/running/${r.exp_id}`)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  try {
    models.value = await fetchModels()
  } catch (e) {
    ElMessage.error('无法连接后端服务，请确认后端已启动（端口 8210）')
  } finally {
    loadingModels.value = false
  }
  await refreshDataStatus()
})
</script>

<style scoped>
.data-alert {
  margin-bottom: 20px;
}
.steps {
  margin: 8px 0 28px;
}
.section-title {
  margin: 20px 0 12px;
  color: #303133;
}
.group-block {
  margin-bottom: 8px;
}
.group-tag {
  margin-bottom: 10px;
}
.model-card {
  margin-bottom: 16px;
  cursor: pointer;
  border: 2px solid transparent;
  transition: border-color 0.2s;
}
.model-card.selected {
  border-color: #1f6feb;
}
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.model-name {
  font-weight: 600;
}
.model-desc {
  font-size: 12px;
  color: #909399;
  line-height: 1.6;
  min-height: 38px;
}
.param-card {
  max-width: 720px;
}
.param-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.tip-icon {
  color: #909399;
  cursor: help;
}
.no-data-tip {
  margin-left: 12px;
  color: #e6a23c;
  font-size: 13px;
}
.loading-box {
  max-width: 600px;
}
</style>
