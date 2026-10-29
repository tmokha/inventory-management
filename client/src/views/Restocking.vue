<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <div v-if="placedOrder" class="success-banner">
        <span>{{ t('restocking.orderPlaced', { orderNumber: placedOrder.order_number }) }}</span>
        <router-link to="/orders">{{ t('restocking.viewOrders') }}</router-link>
      </div>
      <div v-if="submitError" class="error">{{ submitError }}</div>

      <div class="card budget-card">
        <div class="budget-row">
          <label for="budget-slider" class="budget-label">{{ t('restocking.budget') }}</label>
          <span class="budget-value">{{ formatMoney(budget) }}</span>
        </div>
        <input
          id="budget-slider"
          v-model.number="budget"
          type="range"
          min="0"
          :max="maxBudget"
          :step="budgetStep"
          class="budget-slider"
        />
        <div class="budget-scale">
          <span>{{ formatMoney(0) }}</span>
          <span>{{ formatMoney(maxBudget) }}</span>
        </div>
        <p class="budget-hint">{{ t('restocking.budgetHint') }}</p>
      </div>

      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.itemsRecommended') }}</div>
          <div class="stat-value">{{ recommendations.length }}</div>
        </div>
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.totalCost') }}</div>
          <div class="stat-value">{{ formatMoney(totalCost) }}</div>
        </div>
        <div class="stat-card success">
          <div class="stat-label">{{ t('restocking.remainingBudget') }}</div>
          <div class="stat-value">{{ formatMoney(remainingBudget) }}</div>
        </div>
        <div class="stat-card warning">
          <div class="stat-label">{{ t('restocking.deliveryLeadTime') }}</div>
          <div class="stat-value">{{ t('restocking.daysCount', { count: maxLeadTime }) }}</div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.recommendations') }} ({{ recommendations.length }})</h3>
          <button
            type="button"
            class="place-order-btn"
            :disabled="recommendations.length === 0 || submitting"
            @click="placeOrder"
          >
            {{ submitting ? t('restocking.submitting') : t('restocking.placeOrder') }}
          </button>
        </div>

        <div v-if="candidates.length === 0" class="empty">{{ t('restocking.noCandidates') }}</div>
        <div v-else-if="recommendations.length === 0" class="empty">{{ t('restocking.noRecommendations') }}</div>
        <div v-else class="table-container">
          <table>
            <thead>
              <tr>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.item') }}</th>
                <th>{{ t('restocking.table.trend') }}</th>
                <th class="num">{{ t('restocking.table.quantity') }}</th>
                <th class="num">{{ t('restocking.table.unitCost') }}</th>
                <th class="num">{{ t('restocking.table.lineTotal') }}</th>
                <th class="num">{{ t('restocking.table.leadTime') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="rec in recommendations" :key="rec.sku">
                <td><strong>{{ rec.sku }}</strong></td>
                <td>{{ translateProductName(rec.name) }}</td>
                <td>
                  <span :class="['badge', rec.trend]">{{ t(`trends.${rec.trend}`) }}</span>
                </td>
                <td class="num">
                  {{ rec.quantity.toLocaleString() }}
                  <span v-if="rec.partial" class="badge partial">{{ t('restocking.partial') }}</span>
                </td>
                <td class="num">{{ formatMoney(rec.unit_cost, 2) }}</td>
                <td class="num"><strong>{{ formatMoney(rec.lineTotal, 2) }}</strong></td>
                <td class="num">{{ t('restocking.daysCount', { count: rec.lead_time_days }) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'
import { formatCurrencyWithDecimals } from '../utils/currency'

const { t, currentCurrency, translateProductName } = useI18n()

// Raw data
const forecasts = ref([])
const loading = ref(true)
const error = ref(null)
const budget = ref(0)
const submitting = ref(false)
const submitError = ref(null)
const placedOrder = ref(null)

// Money is held in USD (as the API returns it); conversion to JPY is display-only.
const formatMoney = (value, decimals = 0) =>
  formatCurrencyWithDecimals(value, currentCurrency.value, decimals)

const toCents = (value) => Math.round(value * 100)

// Items whose forecast exceeds current demand, highest percent increase first.
const candidates = computed(() => {
  return forecasts.value
    .map(f => {
      const gap = f.forecasted_demand - f.current_demand
      // Guard against divide-by-zero: treat zero current demand as the largest increase
      const pct = f.current_demand > 0 ? gap / f.current_demand : Infinity
      return { ...f, gap, pct }
    })
    .filter(c => c.gap > 0 && c.unit_cost > 0)
    .sort((a, b) => b.pct - a.pct)
})

const maxBudget = computed(() => {
  const total = candidates.value.reduce((sum, c) => sum + c.gap * c.unit_cost, 0)
  return Math.ceil(total)
})

const budgetStep = computed(() => {
  if (maxBudget.value > 100000) return 100
  if (maxBudget.value > 10000) return 10
  return 1
})

// Greedy fill in priority order, working in integer cents to avoid float drift
// so the total can never exceed the budget. If the full gap does not fit, buy as
// many whole units as the remaining budget allows, then keep going: a later,
// cheaper item may still fit.
const recommendations = computed(() => {
  let remainingCents = toCents(budget.value)
  const result = []
  for (const c of candidates.value) {
    const unitCents = toCents(c.unit_cost)
    if (unitCents <= 0) continue
    const fullCents = c.gap * unitCents
    let quantity = 0
    if (fullCents <= remainingCents) {
      quantity = c.gap
    } else {
      quantity = Math.floor(remainingCents / unitCents)
    }
    if (quantity <= 0) continue
    const lineCents = quantity * unitCents
    remainingCents -= lineCents
    result.push({
      sku: c.item_sku,
      name: c.item_name,
      trend: c.trend,
      quantity,
      unit_cost: c.unit_cost,
      lead_time_days: c.lead_time_days,
      lineTotal: lineCents / 100,
      partial: quantity < c.gap
    })
  }
  return result
})

const totalCost = computed(() => {
  // Sum in cents, then convert once
  return recommendations.value.reduce((sum, r) => sum + toCents(r.lineTotal), 0) / 100
})

const remainingBudget = computed(() => (toCents(budget.value) - toCents(totalCost.value)) / 100)

const maxLeadTime = computed(() =>
  recommendations.value.reduce((max, r) => Math.max(max, r.lead_time_days), 0)
)

const loadData = async () => {
  try {
    loading.value = true
    error.value = null
    forecasts.value = await api.getDemandForecasts()
    // Default to roughly half of the max, snapped to the slider step
    budget.value = Math.round(maxBudget.value / 2 / budgetStep.value) * budgetStep.value
  } catch (err) {
    error.value = t('restocking.loadFailed') + ': ' + err.message
    console.error('Load error:', err)
  } finally {
    loading.value = false
  }
}

const placeOrder = async () => {
  if (recommendations.value.length === 0 || submitting.value) return
  submitting.value = true
  submitError.value = null
  placedOrder.value = null
  try {
    placedOrder.value = await api.createRestockingOrder({
      budget: budget.value,
      items: recommendations.value.map(r => ({ sku: r.sku, quantity: r.quantity }))
    })
  } catch (err) {
    submitError.value = err.response?.data?.detail || t('restocking.orderFailed')
    console.error('Order error:', err)
  } finally {
    submitting.value = false
  }
}

onMounted(loadData)
</script>

<style scoped>
.budget-card {
  padding: 1.25rem 1.5rem;
  margin-bottom: 1.5rem;
}

.budget-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 0.75rem;
}

.budget-label {
  font-weight: 600;
  color: #0f172a;
}

.budget-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: #0f172a;
}

.budget-slider {
  width: 100%;
  accent-color: #3b82f6;
}

.budget-scale {
  display: flex;
  justify-content: space-between;
  font-size: 0.813rem;
  color: #64748b;
}

.budget-hint {
  margin: 0.5rem 0 0;
  font-size: 0.813rem;
  color: #64748b;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.place-order-btn {
  background: #0f172a;
  color: white;
  border: none;
  border-radius: 6px;
  padding: 0.5rem 1.25rem;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
}

.place-order-btn:hover:not(:disabled) {
  background: #1e293b;
}

.place-order-btn:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}

.num {
  text-align: right;
}

.badge.partial {
  background: #f1f5f9;
  color: #64748b;
  margin-left: 0.375rem;
}

.empty {
  padding: 2rem;
  text-align: center;
  color: #64748b;
}

.success-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  color: #166534;
  padding: 1rem;
  border-radius: 8px;
  margin-bottom: 1rem;
  font-size: 0.938rem;
}

.success-banner a {
  color: #166534;
  font-weight: 600;
}
</style>
