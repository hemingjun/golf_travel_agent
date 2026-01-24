"""Self-healing LLM wrapper for Gemini MALFORMED_FUNCTION_CALL errors

Wraps ChatGoogleGenerativeAI to detect and retry malformed tool calls.
The wrapper intercepts responses with MALFORMED_FUNCTION_CALL finish_reason
and automatically retries with a guidance prompt.
"""

from typing import Any, Iterator, List, Optional, Sequence

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import RunnableSerializable
from langchain_core.runnables.config import RunnableConfig
from langchain_google_genai import ChatGoogleGenerativeAI

from .debug import debug_print

# Error states that indicate a malformed response
MALFORMED_FINISH_REASONS = frozenset({"MALFORMED_FUNCTION_CALL", "OTHER"})

# Retry prompt injected to guide the model to fix its response
RETRY_PROMPT = """Your previous response contained a malformed function call.
Please try again with a properly formatted tool call. Ensure:
1. Function name matches available tools exactly
2. All required arguments are provided with correct types
3. JSON structure is valid

If tool calling fails, respond with a text message instead."""


class SelfHealingGemini(RunnableSerializable[List[BaseMessage], AIMessage]):
    """Wrapper around ChatGoogleGenerativeAI with automatic retry for malformed responses.

    This wrapper detects MALFORMED_FUNCTION_CALL errors and automatically retries
    with a helpful prompt to guide the model toward a valid response.

    If the primary model fails after all retries, it falls back to a secondary model
    for one final attempt before returning the fallback response.

    Implements the Runnable protocol for compatibility with LangChain/LangGraph.
    """

    llm: Any  # ChatGoogleGenerativeAI or RunnableBinding
    fallback_llm: Any = None  # Fallback model when primary fails
    max_retries: int = 2

    class Config:
        arbitrary_types_allowed = True

    @property
    def InputType(self) -> type:
        return List[BaseMessage]

    @property
    def OutputType(self) -> type:
        return AIMessage

    def _is_malformed_response(self, response: AIMessage) -> bool:
        """Check if the response indicates a malformed function call."""
        # Check response_metadata for finish_reason
        if hasattr(response, "response_metadata") and response.response_metadata:
            finish_reason = response.response_metadata.get("finish_reason", "")
            if finish_reason in MALFORMED_FINISH_REASONS:
                debug_print(f"[LLM] Malformed: finish_reason={finish_reason}")
                return True

        # Empty response with 0 tokens is suspicious
        if not response.content and not response.tool_calls:
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                if response.usage_metadata.get("output_tokens", 1) == 0:
                    debug_print("[LLM] Malformed: empty response, 0 tokens")
                    return True

        # Has invalid_tool_calls populated
        if getattr(response, "invalid_tool_calls", None):
            debug_print(
                f"[LLM] Malformed: invalid_tool_calls={response.invalid_tool_calls}"
            )
            return True

        # Empty content list (Gemini sometimes returns [])
        if isinstance(response.content, list):
            if len(response.content) == 0:
                debug_print("[LLM] Malformed: empty content list")
                return True

            # List with no valid text content
            has_text = any(
                isinstance(item, str) and item.strip()
                or (isinstance(item, dict) and item.get("type") == "text" and item.get("text", "").strip())
                for item in response.content
            )
            if not has_text:
                debug_print("[LLM] Malformed: no text content in list")
                return True

        return False

    def _build_retry_messages(
        self, messages: List[BaseMessage], failed: AIMessage
    ) -> List[BaseMessage]:
        """Build message list for retry attempt."""
        result = list(messages)
        if failed.content:
            result.append(failed)
        result.append(HumanMessage(content=RETRY_PROMPT))
        return result

    def _create_fallback_response(self) -> AIMessage:
        """Create a graceful fallback response when all retries fail."""
        return AIMessage(
            content="抱歉，系统遇到技术问题。请重新描述您的需求或稍后再试。",
            response_metadata={"finish_reason": "FALLBACK_AFTER_RETRIES"},
        )

    def invoke(
        self,
        input: List[BaseMessage],
        config: Optional[RunnableConfig] = None,
        **kwargs: Any,
    ) -> AIMessage:
        """Invoke with automatic retry on malformed responses."""
        messages = input
        last_response = None

        for attempt in range(self.max_retries + 1):
            if attempt == 0:
                current_messages = messages
            else:
                debug_print(f"[LLM] Retry {attempt}/{self.max_retries}")
                failed_msg = last_response if last_response else AIMessage(content="")
                current_messages = self._build_retry_messages(messages, failed_msg)

            try:
                response = self.llm.invoke(current_messages, config=config, **kwargs)

                if not self._is_malformed_response(response):
                    return response

                last_response = response
            except Exception as e:
                debug_print(f"[LLM] Error attempt {attempt + 1}: {e}")
                if attempt >= self.max_retries:
                    raise

        # Primary model failed, try fallback model
        if self.fallback_llm:
            debug_print("[LLM] Primary model failed, trying fallback model")
            try:
                response = self.fallback_llm.invoke(messages, config=config, **kwargs)
                if not self._is_malformed_response(response):
                    debug_print("[LLM] Fallback model succeeded")
                    return response
                debug_print("[LLM] Fallback model also returned malformed response")
            except Exception as e:
                debug_print(f"[LLM] Fallback model error: {e}")

        debug_print("[LLM] All attempts failed, returning fallback response")
        return self._create_fallback_response()

    async def ainvoke(
        self,
        input: List[BaseMessage],
        config: Optional[RunnableConfig] = None,
        **kwargs: Any,
    ) -> AIMessage:
        """Async invoke with automatic retry on malformed responses."""
        messages = input
        last_response = None

        for attempt in range(self.max_retries + 1):
            if attempt == 0:
                current_messages = messages
            else:
                debug_print(f"[LLM] Async retry {attempt}/{self.max_retries}")
                failed_msg = last_response if last_response else AIMessage(content="")
                current_messages = self._build_retry_messages(messages, failed_msg)

            try:
                response = await self.llm.ainvoke(
                    current_messages, config=config, **kwargs
                )

                if not self._is_malformed_response(response):
                    return response

                last_response = response
            except Exception as e:
                debug_print(f"[LLM] Async error attempt {attempt + 1}: {e}")
                if attempt >= self.max_retries:
                    raise

        # Primary model failed, try fallback model
        if self.fallback_llm:
            debug_print("[LLM] Async primary model failed, trying fallback model")
            try:
                response = await self.fallback_llm.ainvoke(
                    messages, config=config, **kwargs
                )
                if not self._is_malformed_response(response):
                    debug_print("[LLM] Async fallback model succeeded")
                    return response
                debug_print("[LLM] Async fallback model also returned malformed response")
            except Exception as e:
                debug_print(f"[LLM] Async fallback model error: {e}")

        debug_print("[LLM] Async all attempts failed, returning fallback response")
        return self._create_fallback_response()

    def stream(
        self,
        input: List[BaseMessage],
        config: Optional[RunnableConfig] = None,
        **kwargs: Any,
    ) -> Iterator[AIMessageChunk]:
        """Stream responses - delegates to underlying LLM without retry logic.

        Note: Streaming does not support automatic retry for malformed responses
        since we cannot detect the finish_reason until the stream completes.
        """
        yield from self.llm.stream(input, config=config, **kwargs)

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "SelfHealingGemini":
        """Bind tools to underlying LLM and return a new wrapper instance."""
        bound = self.llm.bind_tools(tools, **kwargs)
        fallback_bound = (
            self.fallback_llm.bind_tools(tools, **kwargs)
            if self.fallback_llm
            else None
        )
        return SelfHealingGemini(
            llm=bound,
            fallback_llm=fallback_bound,
            max_retries=self.max_retries,
        )

    # Required for BaseChatModel compatibility in create_react_agent
    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Generate method for BaseChatModel compatibility."""
        response = self.invoke(messages, stop=stop, **kwargs)
        gen_info = {}
        if hasattr(response, "response_metadata"):
            gen_info = {
                "finish_reason": response.response_metadata.get("finish_reason", "")
            }
        return ChatResult(
            generations=[ChatGeneration(message=response, generation_info=gen_info)]
        )

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        """Stream method for BaseChatModel compatibility."""
        for chunk in self.stream(messages, stop=stop, **kwargs):
            yield ChatGenerationChunk(message=chunk)

    @property
    def _llm_type(self) -> str:
        """Return type identifier for the LLM."""
        return "self-healing-gemini"


def create_self_healing_llm(
    model: str = "gemini-3-flash-preview",
    fallback_model: str = "gemini-2.5-flash",
    temperature: float = 0.1,
    request_timeout: int = 60,
    max_retries: int = 2,
    **kwargs: Any,
) -> SelfHealingGemini:
    """Factory function to create a self-healing Gemini LLM.

    Args:
        model: Primary Gemini model ID
        fallback_model: Fallback model ID when primary fails (set to None to disable)
        temperature: Sampling temperature
        request_timeout: Request timeout in seconds
        max_retries: Maximum retry attempts for malformed responses
        **kwargs: Additional arguments passed to ChatGoogleGenerativeAI

    Returns:
        SelfHealingGemini wrapper instance
    """
    base_llm = ChatGoogleGenerativeAI(
        model=model,
        temperature=temperature,
        request_timeout=request_timeout,
        **kwargs,
    )

    fallback_llm = None
    if fallback_model:
        fallback_llm = ChatGoogleGenerativeAI(
            model=fallback_model,
            temperature=temperature,
            request_timeout=request_timeout,
            **kwargs,
        )
        debug_print(f"[LLM] Created with fallback model: {fallback_model}")

    return SelfHealingGemini(
        llm=base_llm,
        fallback_llm=fallback_llm,
        max_retries=max_retries,
    )
