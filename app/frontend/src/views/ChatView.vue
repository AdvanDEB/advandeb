<template>
  <!-- The page's heading (F-030): the chat layout has no visible title, but a
       screen reader's heading list and the route focus need one. -->
  <h1 class="sr-only">Chat</h1>
  <ChatInterface />
</template>

<script setup lang="ts">
import ChatInterface from '@/components/chat/ChatInterface.vue'
</script>
