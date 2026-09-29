<template>
  <el-container class="layout">
    <el-header class="header">
      <div class="brand" @click="$router.push('/')">
        <el-icon :size="22" color="#1f6feb"><TrendCharts /></el-icon>
        <span class="brand-name">Qlib 量化实验平台</span>
      </div>
      <el-menu mode="horizontal" router :default-active="$route.path" class="menu" :ellipsis="false">
        <el-menu-item index="/">新建实验</el-menu-item>
        <el-menu-item index="/history">历史实验</el-menu-item>
        <el-menu-item index="/data">数据管理</el-menu-item>
      </el-menu>
    </el-header>
    <el-main class="main">
      <router-view />
    </el-main>
  </el-container>
</template>

<script setup lang="ts">
import { TrendCharts } from '@element-plus/icons-vue'
</script>

<style scoped>
.layout {
  min-height: 100vh;
}
.header {
  display: flex;
  align-items: center;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  padding: 0 24px;
}
.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  margin-right: 32px;
}
.brand-name {
  font-size: 17px;
  font-weight: 600;
  color: #1f6feb;
}
.menu {
  flex: 1;
  border-bottom: none;
}
.main {
  max-width: 1200px;
  margin: 0 auto;
  width: 100%;
  padding: 24px;
}
</style>
