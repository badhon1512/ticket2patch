# Ticket2Patch agent

Ticket2Patch follows the reference backend's explicit agent organization:

```text
agents/
|-- agent.py          # Ticket2PatchAgent and LangGraph assembly
|-- state.py          # Typed graph state and reducers
|-- guardrails.py     # Eligibility, risk, and protected-action checks
|-- prompts.py        # Versioned system and task instructions
`-- nodes/            # Bounded workflow node implementations
```

The `Ticket2PatchAgent` is an executable class-based LangGraph. It receives its
model, eligibility policy, read-only tools, and checkpointer through dependency
injection and compiles the graph during initialization.

```text
ingest -> guardrails -> investigate -> reproduce -> plan -> approval
       -> patch -> validate -> review -> publication approval -> draft PR
```

Read-only investigation tools and write-capable publication tools will remain
separate. Consequential actions will be protected by LangGraph interrupts and
deterministic policy checks.

The first graph intentionally stops after investigation:

```text
START
  -> eligibility_check
      -> END when ineligible
      -> call_llm when eligible
          -> read_tool_calls when requested
          -> call_llm
          -> END when the investigation response is ready
```

Patch, validation, approval, and publication nodes will be added as bounded
workflow stages rather than exposed through the generic tool loop.

## Defined contract

- Mission: turn an eligible production ticket into a validated patch and
  approved draft pull request.
- Inputs: a normalized ticket snapshot, repository mapping, evidence sources,
  policy configuration, and an isolated workspace.
- Outputs: an investigation report, reproduction result, proposed plan, patch,
  validation results, review findings, and optionally a draft PR.
- Hard limits: no production access, secret access, unscoped filesystem writes,
  unapproved pushes, merges, or deployments.
- Authorization: deterministic policy first; the model never grants itself
  permission.
