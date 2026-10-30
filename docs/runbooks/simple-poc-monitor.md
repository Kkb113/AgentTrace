# Run the POC monitor

Use the existing operator session on this PC. No Administrator PowerShell, account creation, service installation or new Azure resource is needed.

From `C:\AgentDetection`, start the qualified monitor:

```powershell
uv run --frozen python scripts/monitor-outlook-mail.py --config work/private/agent-provider-monitor/runtime.private.json --dry-run
```

Leave it running and stop it with **Ctrl+C**. Restart with the same command and configuration to resume the saved mailbox checkpoints. Outlook can be closed. The PC and Python process must remain running; this does not promise continued operation through Windows sign-out or shutdown.

To run one collection cycle for a check, append `--once`. To validate configuration without mailbox access, append `--check`.

After stopping the monitor, inspect stored classifications and evidence references:

```powershell
uv run --frozen python scripts/monitor-outlook-mail.py --config work/private/agent-provider-monitor/runtime.private.json --inspect-rules
```

Inspection displays stored assessments and does not refresh evidence. A `cycle_completed` message reports local collection/decision progress; it does not mean that an Outlook category was applied. Use the [existing scoped category-writer procedure](outlook-category-writer.md) for explicit category application; automatic category rollout remains gated by the remaining Outlook validation/pilot work.

The existing synthetic subject prefix and enrolled receiving folders still define the POC population. AgentTrace does not send test mail. Agent attribution can wait for audit evidence; generic Gmail API traffic alone remains Unknown. Authentication/network failures are reported as failures or evidence gaps, not proof of a human or agent.

The incremental Azure resource cost for this method is **₹0/month**. Existing storage/logging resources can still incur usage charges, and existing Microsoft 365 licences and PC electricity are excluded. No new licence purchase, VM, database or publisher-reader grant is needed.
