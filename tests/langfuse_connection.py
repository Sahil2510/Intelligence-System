from app.prompts.langfuse_client import langfuse
from app.prompts.prompt_registry import PromptRegistry


print("Checking Langfuse auth...")

if langfuse.auth_check():
    print("Langfuse connected")
else:
    print("Langfuse authentication failed")

registry = PromptRegistry()

print("\nSYSTEM PROMPT:")
print(registry.system_prompt())

print("\nWEB SEARCH PROMPT:")
print(registry.web_search_prompt())

print("\nHOLDING RESPONSE PROMPT:")
print(registry.holding_response_prompt())