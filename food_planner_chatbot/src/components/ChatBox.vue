<script setup>
import { ref, onMounted, nextTick, watch } from 'vue'

const STORAGE_KEY = 'food-planner-messages'

const draft = ref('')
const messages = ref([])
const listEl = ref(null)

onMounted(() => {
  try {
    messages.value = JSON.parse(localStorage.getItem(STORAGE_KEY)) ?? []
  } catch {
    messages.value = []
  }
  scrollToBottom()
})

watch(
  messages,
  (value) => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(value))
    } catch {
      // storage unavailable (private mode, quota) — keep the in-memory log
    }
  },
  { deep: true },
)

async function scrollToBottom() {
  await nextTick()
  if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight
}

function submit() {
  const text = draft.value.trim()
  if (!text) return

  messages.value.push({
    id: crypto.randomUUID(),
    role: 'user',
    text,
    at: new Date().toISOString(),
  })
  draft.value = ''
  scrollToBottom()

  // Later: send `text` to the LLM and push the reply as { role: 'assistant', ... }
}

function clearAll() {
  messages.value = []
}

function formatTime(iso) {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}
</script>

<template>
  <section class="chat">
    <header class="chat__header">
      <h2>Food planner</h2>
      <button v-if="messages.length" type="button" class="chat__clear" @click="clearAll">
        Clear
      </button>
    </header>

    <div ref="listEl" class="chat__list">
      <p v-if="!messages.length" class="chat__empty">No messages yet. Write something below.</p>
      <article v-for="message in messages" :key="message.id" class="chat__message">
        <p class="chat__text">{{ message.text }}</p>
        <time class="chat__time" :datetime="message.at">{{ formatTime(message.at) }}</time>
      </article>
    </div>

    <form class="chat__form" @submit.prevent="submit">
      <textarea
        v-model="draft"
        class="chat__input"
        rows="2"
        placeholder="What do you want to eat this week?"
        @keydown.enter.exact.prevent="submit"
      ></textarea>
      <button type="submit" class="chat__submit" :disabled="!draft.trim()">Send</button>
    </form>
  </section>
</template>

<style scoped>
.chat {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  max-width: 40rem;
  height: 32rem;
  margin: 2rem auto;
  padding: 1rem;
  border: 1px solid #d8d8d2;
  border-radius: 0.75rem;
  font-family: system-ui, sans-serif;
}

.chat__header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
}

.chat__header h2 {
  margin: 0;
  font-size: 1rem;
  letter-spacing: 0.02em;
}

.chat__clear {
  border: none;
  background: none;
  color: #8a8a80;
  font-size: 0.8rem;
  cursor: pointer;
}

.chat__clear:hover {
  color: #3a3a35;
}

.chat__list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.chat__empty {
  margin: auto;
  color: #9a9a90;
  font-size: 0.875rem;
}

.chat__message {
  align-self: flex-end;
  max-width: 80%;
  padding: 0.5rem 0.75rem;
  border-radius: 0.75rem 0.75rem 0.125rem 0.75rem;
  background: #eceae4;
}

.chat__text {
  margin: 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.chat__time {
  display: block;
  margin-top: 0.25rem;
  color: #8a8a80;
  font-size: 0.7rem;
}

.chat__form {
  display: flex;
  gap: 0.5rem;
  align-items: flex-end;
}

.chat__input {
  flex: 1;
  padding: 0.5rem;
  border: 1px solid #d8d8d2;
  border-radius: 0.5rem;
  font: inherit;
  resize: none;
}

.chat__input:focus {
  outline: 2px solid #b9b6ab;
  outline-offset: -1px;
}

.chat__submit {
  padding: 0.5rem 1rem;
  border: none;
  border-radius: 0.5rem;
  background: #3a3a35;
  color: #fff;
  font: inherit;
  cursor: pointer;
}

.chat__submit:disabled {
  background: #c8c6c0;
  cursor: not-allowed;
}
</style>
