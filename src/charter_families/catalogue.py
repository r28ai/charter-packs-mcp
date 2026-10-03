# SPDX-FileCopyrightText: 2026 R28 AI, Inc.
# SPDX-License-Identifier: Apache-2.0

"""The workflows each family serves as MCP prompts.

One entry per workflow: a title, the tools it calls in order as
``"pack.tool"``, why it is worth running, and how often it usually is. The
steps are guidance for the agent rather than a script - the agent decides
which to repeat, skip or reorder - so nothing here is orchestration. What is
fixed is that every step names a tool the pack ships, which
``tests/test_families.py`` checks against the packs themselves.
"""

from __future__ import annotations

from typing import Dict, Tuple

# (title, steps, why, cadence)
Entry = Tuple[str, str, str, str]

CATALOGUE: Dict[str, Tuple[Entry, ...]] = {
    "engineering": (
        (
            "Failing CI → bug with the log excerpt",
            (
                "github.actions_list_workflow_runs > "
                "github.actions_list_jobs_for_run > github.actions_download_job_logs > "
                "linear.issue_create > slack.chat_post_message"
            ),
            (
                "A red main branch becomes an owned issue with the failing step quoted, "
                "not a channel ping."
            ),
            "per event",
        ),
        (
            "Link every PR to its Linear issue",
            (
                "github.pulls_list > linear.attachments_for_url > "
                "linear.search_issues > linear.attachment_create"
            ),
            "No orphan PRs, so cycle reports and changelogs stop missing work.",
            "daily",
        ),
        (
            "Security alerts → Linear",
            (
                "github.dependabot_list_alerts > github.code_scanning_list_alerts > "
                "linear.search_issues > linear.issue_create"
            ),
            ("Critical alerts get owners and due dates in the tracker the team actually reads."),
            "daily",
        ),
        (
            "Leaked secret → page a human",
            ("github.secret_scanning_list_alerts > linear.issue_create > slack.chat_post_message"),
            "An exposed key is an urgent issue and a loud message within minutes.",
            "hourly",
        ),
        (
            "Release → changelog page and announcement",
            (
                "github.releases_get_latest > github.repos_compare_commits > "
                "notion.pages_create > slack.chat_post_message"
            ),
            ("Every release has a readable changelog without a release manager writing it."),
            "per release",
        ),
        (
            "Standup digest per person",
            (
                "github.search_issues > linear.issues_list > "
                "slack.conversations_open > slack.chat_post_message"
            ),
            ("Yesterday's PRs and today's issues in a DM, so standup is about blockers."),
            "daily",
        ),
        (
            "Stale review nudger",
            (
                "github.pulls_list > github.pulls_list_requested_reviewers > "
                "slack.users_list > slack.conversations_open > slack.chat_post_message"
            ),
            "PRs waiting more than a day get a polite DM to the right reviewer.",
            "daily",
        ),
        (
            "Linear issue → branch and draft PR",
            (
                "linear.issue_get > github.git_refs_get > github.git_refs_create > "
                "github.pulls_create > linear.attachment_create"
            ),
            "Starting work on an issue sets up the branch, the PR and the link.",
            "on demand",
        ),
        (
            "Incident timeline → postmortem draft",
            (
                "slack.conversations_history > github.repos_list_commits > "
                "github.actions_list_workflow_runs > gdocs.documents_create > "
                "linear.issue_create"
            ),
            (
                "The timeline is assembled from what happened, and action items are "
                "tracked from minute one."
            ),
            "per incident",
        ),
        (
            "Postmortem actions tracked to done",
            (
                "gdocs.documents_get > linear.issue_create > "
                "linear.issue_relation_create > gcalendar.events_insert"
            ),
            "Follow-ups from the postmortem become linked issues with a review date.",
            "per incident",
        ),
        (
            "Slack bug report → Linear",
            (
                "slack.conversations_replies > linear.issue_create > "
                "linear.attachment_create > slack.chat_post_message"
            ),
            ("The thread becomes an issue with repro steps, and the thread gets the link."),
            "per event",
        ),
        (
            "GitHub issues mirrored into Linear",
            (
                "github.issues_list_for_repo > linear.search_issues > "
                "linear.issue_create > github.issues_create_comment"
            ),
            "Open-source reports enter the internal tracker without double triage.",
            "daily",
        ),
        (
            "Vendor deprecation → affected files",
            (
                "firecrawl.monitor_create > firecrawl.monitor_checks_list > "
                "github.search_code > linear.issue_create"
            ),
            ("A deprecation notice arrives already mapped to the code that uses the old API."),
            "daily",
        ),
        (
            "On-call handoff",
            (
                "gcalendar.events_list > linear.issues_list > "
                "github.notifications_list > slack.chat_post_message"
            ),
            ("The next on-call starts with open urgents and unread alerts in one message."),
            "weekly",
        ),
        (
            "Deploy approval from Slack",
            (
                "github.actions_list_pending_deployments > slack.chat_post_message > "
                "slack.conversations_replies > "
                "github.actions_review_pending_deployments"
            ),
            (
                "Production deploys gated on an explicit 'approve' in a thread, with the "
                "reviewer on record."
            ),
            "per event",
        ),
        (
            "Flaky test ledger",
            (
                "github.actions_list_runs_for_workflow > "
                "github.checks_list_annotations > gsheets.spreadsheets_values_append > "
                "linear.issue_create"
            ),
            (
                "Tests that fail and pass on retry get counted until one crosses the line "
                "and gets an issue."
            ),
            "daily",
        ),
        (
            "CI spend report",
            (
                "github.actions_list_workflow_runs > github.actions_get_run_usage > "
                "gsheets.spreadsheets_values_append > slack.chat_post_message"
            ),
            "Which workflows burn the minutes, weekly, before the bill does it.",
            "weekly",
        ),
        (
            "PR → design note in Docs",
            (
                "github.pulls_get > github.pulls_list_files > github.pulls_get_diff > "
                "gdocs.documents_create"
            ),
            "A large PR gets a readable explanation for reviewers outside the team.",
            "on demand",
        ),
        (
            "Dependency choice with real repo health",
            (
                "tavily.search > github.search_repositories > github.repos_get > "
                "github.repos_list_contributors > notion.pages_create"
            ),
            "Library choices recorded with stars, activity and bus factor, not vibes.",
            "on demand",
        ),
        (
            "Slack debate → ADR in the repo",
            (
                "slack.conversations_replies > github.repos_create_or_update_file > "
                "linear.attachment_create"
            ),
            "The decision and its reasons get committed next to the code they govern.",
            "on demand",
        ),
        (
            "Repo onboarding doc",
            (
                "github.repos_get_readme > github.repos_list_languages > "
                "github.repos_list_contributors > gdocs.documents_create"
            ),
            "A new engineer gets a map of an unfamiliar repo and who to ask.",
            "on demand",
        ),
        (
            "Stale PR cleanup",
            (
                "github.pulls_list > github.issues_create_comment > "
                "github.pulls_update > slack.chat_post_message"
            ),
            (
                "Month-old PRs are closed with a note and the author is told, so the "
                "queue means something."
            ),
            "weekly",
        ),
        (
            "TODO/FIXME debt register",
            (
                "github.search_code > linear.search_issues > linear.issue_create > "
                "gsheets.spreadsheets_values_update"
            ),
            "Debt hiding in comments becomes a list someone can prioritise.",
            "monthly",
        ),
        (
            "Repo docs → engineering wiki",
            ("github.repos_get_content > notion.pages_update_markdown > slack.chat_post_message"),
            "The wiki mirrors docs/ in the repo instead of drifting from it.",
            "per merge",
        ),
        (
            "Release credits for contributors",
            (
                "github.releases_get_latest > github.repos_compare_commits > "
                "github.repos_list_contributors > github.releases_update > "
                "slack.chat_post_message"
            ),
            "Every release thanks the people who made it, by name.",
            "per release",
        ),
    ),
    "product": (
        (
            "Call notes → deduped Linear issues",
            (
                "granola.notes_list > granola.notes_get > linear.search_issues > "
                "linear.issue_create > slack.chat_post_message"
            ),
            (
                "Feature requests from yesterday's calls land as issues, matched against "
                "what already exists, and #product sees the list."
            ),
            "daily",
        ),
        (
            "Customer requests attached to the issue they ask for",
            (
                "granola.notes_get > linear.customers_list > linear.search_issues > "
                "linear.customer_need_create"
            ),
            ("The roadmap gets ranked by who asked, not by who spoke loudest in planning."),
            "per call",
        ),
        (
            "Discovery calls → PRD draft",
            (
                "granola.notes_list > granola.notes_transcript_get > "
                "gdocs.documents_create > gdocs.documents_batch_update"
            ),
            (
                "A first PRD drafted from five interviews, with quotes, before the PM "
                "opens a blank doc."
            ),
            "on demand",
        ),
        (
            "PRD doc → Linear project, milestones and issues",
            (
                "gdocs.documents_get > linear.project_create > "
                "linear.project_milestone_create > linear.issue_create"
            ),
            ("The spec turns into a plan in one pass instead of an afternoon of copy-paste."),
            "on demand",
        ),
        (
            "Notion spec → Linear issues, linked back",
            (
                "notion.pages_retrieve_markdown > linear.project_create > "
                "linear.issue_create > notion.comments_create"
            ),
            "Teams that write in Notion and ship in Linear stop keeping two lists.",
            "on demand",
        ),
        (
            "Weekly project update, written from the work",
            (
                "linear.project_get > linear.issues_list > github.pulls_list > "
                "linear.project_update_create > slack.chat_post_message"
            ),
            (
                "The update reports what merged and what slipped, with health set from "
                "evidence rather than optimism."
            ),
            "weekly",
        ),
        (
            "Roadmap sheet that keeps itself true",
            (
                "linear.projects_list > linear.project_milestones_list > "
                "gsheets.spreadsheets_values_update"
            ),
            "Leadership keeps its spreadsheet and the spreadsheet stops lying.",
            "daily",
        ),
        (
            "Feedback form → triaged customer needs",
            (
                "gforms.forms_responses_list > linear.search_issues > "
                "linear.customer_need_create > gsheets.spreadsheets_values_append"
            ),
            (
                "Every response is either attached to an issue or logged as new, never "
                "left in a tab."
            ),
            "daily",
        ),
        (
            "#feedback channel → Linear",
            (
                "slack.conversations_history > linear.search_issues > "
                "linear.issue_create > slack.reactions_add"
            ),
            (
                "Feedback posted in Slack gets an issue and a checkmark, so nobody "
                "wonders if it was seen."
            ),
            "daily",
        ),
        (
            "Competitor changelog watch",
            (
                "firecrawl.monitor_create > firecrawl.monitor_checks_list > "
                "linear.issue_create > slack.chat_post_message"
            ),
            (
                "A competitor ships something and a scoped issue exists before the sales "
                "team asks about it."
            ),
            "daily",
        ),
        (
            "Cycle review doc and retro booking",
            (
                "linear.cycle_get > linear.issues_list > gdocs.documents_create > "
                "gcalendar.events_insert"
            ),
            ("Planned vs. done vs. carried over, written up and on the calendar before the retro."),
            "per cycle",
        ),
        (
            "Customer interview program",
            (
                "gforms.forms_create > gforms.forms_responses_list > "
                "gcalendar.events_insert > gmail.messages_send"
            ),
            (
                "Screener, scheduling and confirmations for ten interviews without a "
                "scheduling tool."
            ),
            "on demand",
        ),
        (
            "Research synthesis from a folder of calls",
            (
                "granola.folders_list > granola.notes_list > granola.notes_get > "
                "notion.pages_create > linear.customer_need_create"
            ),
            ("Twenty calls become one synthesis page with every claim traceable to a note."),
            "on demand",
        ),
        (
            "Requests ranked by revenue",
            (
                "linear.customer_needs_list > linear.customers_list > "
                "stripe.customers_list > stripe.subscriptions_list > "
                "gsheets.spreadsheets_values_update"
            ),
            "Each feature request carries the MRR of the customers behind it.",
            "weekly",
        ),
        (
            "Linear customers synced from Stripe",
            (
                "stripe.subscriptions_list > linear.customers_list > "
                "linear.customer_create > linear.customer_update"
            ),
            (
                "Linear's customer tiers and revenue reflect billing, so prioritisation "
                "uses real numbers."
            ),
            "daily",
        ),
        (
            "Shipped → tell everyone who asked",
            (
                "linear.issues_list > linear.customer_needs_list > "
                "linear.customer_get > gmail.drafts_create"
            ),
            (
                "The loop gets closed with every requester, which is the cheapest "
                "retention there is."
            ),
            "weekly",
        ),
        (
            "Launch room in one go",
            (
                "linear.project_get > notion.pages_create > gcalendar.events_insert > "
                "slack.conversations_create > slack.conversations_invite"
            ),
            (
                "Checklist page, launch-day event and channel with the right people, from "
                "the project."
            ),
            "per launch",
        ),
        (
            "Problem-space research brief",
            (
                "tavily.research_create > tavily.research_get > "
                "linear.document_create > slack.chat_post_message"
            ),
            "A cited brief lands in the project's docs before the kickoff meeting.",
            "on demand",
        ),
        (
            "Release notes for customers",
            (
                "linear.issues_list > github.releases_generate_notes > "
                "notion.pages_create > slack.chat_post_message"
            ),
            (
                "Engineering's release notes rewritten for users, from the issues that "
                "actually closed."
            ),
            "per release",
        ),
        (
            "Linear digest to Slack",
            ("linear.issues_list > linear.users_list > slack.users_list > slack.chat_post_message"),
            "What moved, what's stuck, who owns it, with people actually @-mentioned.",
            "daily",
        ),
    ),
    "sales": (
        (
            "Pre-call brief for tomorrow's external meetings",
            (
                "gcalendar.events_list > tavily.search > firecrawl.scrape > "
                "gmail.threads_list > slack.chat_post_message"
            ),
            ("Company news, what they sell and the last email thread, in a DM the night before."),
            "daily",
        ),
        (
            "Call → follow-up email and next step",
            (
                "granola.notes_get > gmail.drafts_create > gcalendar.events_insert > "
                "notion.pages_update"
            ),
            (
                "The recap email is drafted, the next meeting held and the CRM updated "
                "before the rep leaves the room."
            ),
            "per call",
        ),
        (
            "Lead list enrichment",
            (
                "gsheets.spreadsheets_values_get > firecrawl.extract > tavily.search > "
                "gsheets.spreadsheets_values_update"
            ),
            (
                "A column of domains becomes size, product, pricing model and a recent "
                "signal per row."
            ),
            "on demand",
        ),
        (
            "Inbound demo request → booked",
            (
                "gforms.forms_responses_list > firecrawl.scrape > "
                "gcalendar.events_insert > gmail.messages_send > "
                "slack.chat_post_message"
            ),
            "A qualified request gets a meeting and a researched AE within the hour.",
            "hourly",
        ),
        (
            "Scope agreed on a call → payment link",
            (
                "granola.notes_get > stripe.prices_list > "
                "stripe.checkout_sessions_create > gmail.drafts_create"
            ),
            "The deal closes while the buyer still remembers saying yes.",
            "per call",
        ),
        (
            "Signed quote → Stripe invoice",
            (
                "gdocs.documents_get > stripe.customers_create > "
                "stripe.invoice_items_create > stripe.invoices_create > "
                "stripe.invoices_finalize"
            ),
            "The quote's line items become the invoice's, with no retyping.",
            "per deal",
        ),
        (
            "Closed-won handoff",
            (
                "stripe.subscriptions_list > notion.pages_create > "
                "linear.customer_create > slack.conversations_create"
            ),
            ("Account page, customer record and internal channel exist the day the deal closes."),
            "per deal",
        ),
        (
            "Target account research",
            (
                "notion.data_sources_query > tavily.research_create > "
                "tavily.research_get > notion.pages_update"
            ),
            "Every account in the target list gets a cited brief on its page.",
            "weekly",
        ),
        (
            "Pipeline digest",
            ("notion.data_sources_query > gcalendar.events_list > slack.chat_post_message"),
            "Deals with no meeting booked in two weeks get flagged to their owner.",
            "weekly",
        ),
        (
            "Trial ending → rep alert and nudge",
            (
                "stripe.subscriptions_list > stripe.customers_retrieve > "
                "gmail.drafts_create > slack.chat_post_message"
            ),
            ("Trials that end in three days get a human touch instead of a silent expiry."),
            "daily",
        ),
        (
            "No-show recovery",
            "gcalendar.events_list > granola.notes_list > gmail.drafts_create",
            "A meeting with no notes was a no-show, and it gets a reschedule email.",
            "daily",
        ),
        (
            "Security questionnaire, prefilled",
            (
                "gsheets.spreadsheets_values_get > notion.search > gdrive.files_list > "
                "gdrive.files_export > gsheets.spreadsheets_values_update"
            ),
            "Two hundred rows answered from your own policies, for a human to review.",
            "on demand",
        ),
        (
            "New thread from an unknown domain → CRM",
            (
                "gmail.threads_list > notion.data_sources_query > firecrawl.scrape > "
                "notion.pages_create"
            ),
            ("Inbound that didn't come through a form still lands in the CRM with context."),
            "daily",
        ),
        (
            "Mail merge from a sheet",
            (
                "gsheets.spreadsheets_values_get > gmail.drafts_create > "
                "gsheets.spreadsheets_values_update"
            ),
            ("Personalised drafts per row, status written back, nothing sent without review."),
            "on demand",
        ),
    ),
    "marketing": (
        (
            "What shipped → blog and social drafts",
            (
                "linear.issues_list > github.releases_list > gdocs.documents_create > "
                "slack.chat_post_message"
            ),
            "Marketing hears about features from the tracker, not from customers.",
            "weekly",
        ),
        (
            "Competitor pricing tracker",
            (
                "firecrawl.monitor_create > firecrawl.extract > "
                "gsheets.spreadsheets_values_append > slack.chat_post_message"
            ),
            ("Price and packaging changes, dated, in a sheet, with an alert when one moves."),
            "daily",
        ),
        (
            "SEO content gap",
            (
                "firecrawl.map > tavily.search > gsheets.spreadsheets_values_update > "
                "linear.issue_create"
            ),
            ("Topics competitors rank for that you have no page on, as a prioritised backlog."),
            "monthly",
        ),
        (
            "Webinar ops end to end",
            (
                "gforms.forms_create > gforms.forms_responses_list > "
                "gcalendar.events_insert > gmail.messages_send"
            ),
            "Registration, invite and reminders with no webinar tool.",
            "per event",
        ),
        (
            "Customer story pipeline",
            (
                "stripe.customers_list > granola.notes_list > gdocs.documents_create > "
                "gmail.drafts_create"
            ),
            ("Your longest-paying happy customers become case-study drafts and a permission ask."),
            "monthly",
        ),
        (
            "Weekly newsletter draft",
            (
                "linear.issues_list > github.releases_list > "
                "notion.data_sources_query > gdocs.documents_create > "
                "gmail.drafts_create"
            ),
            "Product news, posts and releases gathered into one draft every Friday.",
            "weekly",
        ),
        (
            "Event leads → enriched follow-ups",
            (
                "gforms.forms_responses_list > firecrawl.extract > "
                "notion.pages_create > gmail.drafts_create"
            ),
            "Booth scans become enriched leads with a follow-up waiting, same day.",
            "per event",
        ),
        (
            "Brand mention monitor",
            ("tavily.search > firecrawl.scrape > notion.pages_create > slack.chat_post_message"),
            "Every mention worth replying to shows up with the context to reply.",
            "daily",
        ),
        (
            "Webinar transcript → blog post",
            ("granola.notes_transcript_get > gdocs.documents_create > notion.pages_create"),
            "An hour of talk becomes a post and a queue of social snippets.",
            "per event",
        ),
        (
            "Site QA crawl",
            (
                "firecrawl.crawl > firecrawl.crawl_status > linear.issue_create > "
                "slack.chat_post_message"
            ),
            (
                "Broken links, empty pages and stale pricing get issues before a prospect "
                "finds them."
            ),
            "weekly",
        ),
        (
            "Launch-day pulse",
            ("stripe.checkout_sessions_list > linear.issues_list > slack.chat_schedule_message"),
            (
                "Hourly signups and fresh bugs posted to the launch channel without "
                "anyone refreshing dashboards."
            ),
            "per launch",
        ),
        (
            "Survey → insight memo",
            (
                "gforms.forms_responses_list > gsheets.spreadsheets_values_update > "
                "gdocs.documents_create > slack.chat_post_message"
            ),
            "Raw responses become a tagged sheet and a one-page memo.",
            "per survey",
        ),
        (
            "Docs site freshness check",
            "firecrawl.crawl > github.repos_list_commits > linear.issue_create",
            "Public docs pages older than the code they describe get flagged.",
            "monthly",
        ),
    ),
    "support": (
        (
            "Support email → Linear bug with a reply drafted",
            (
                "gmail.threads_list > gmail.threads_get > linear.search_issues > "
                "linear.issue_create > gmail.drafts_create > gmail.threads_modify"
            ),
            (
                "Bug reports leave the inbox as issues, and the customer gets a real "
                "acknowledgement."
            ),
            "hourly",
        ),
        (
            "Fixed → reply in the original thread",
            (
                "linear.issues_list > linear.attachments_list > gmail.threads_get > "
                "gmail.drafts_create"
            ),
            "Customers who reported a bug hear it's fixed in the same email thread.",
            "daily",
        ),
        (
            "QBR account brief",
            (
                "stripe.customers_retrieve > stripe.invoices_list > "
                "linear.customer_needs_list > granola.notes_list > "
                "gdocs.documents_create"
            ),
            ("Spend, payment issues, open requests and last calls, on one page before the QBR."),
            "per meeting",
        ),
        (
            "Churn signal → save call",
            (
                "stripe.subscriptions_list > granola.notes_list > "
                "slack.chat_post_message > gcalendar.events_insert"
            ),
            "A cancellation at period end triggers a call while there is still time.",
            "daily",
        ),
        (
            "New customer onboarding kickoff",
            (
                "stripe.subscriptions_list > gdrive.files_copy > "
                "gdrive.permissions_create > gcalendar.events_insert > "
                "gmail.messages_send"
            ),
            "Plan doc shared, kickoff booked and welcome sent on day one.",
            "daily",
        ),
        (
            "Customer Slack channel → requests and bugs",
            (
                "slack.conversations_history > linear.customer_need_create > "
                "linear.issue_create > slack.chat_post_message"
            ),
            "Asks in shared channels get tracked and answered with a link.",
            "daily",
        ),
        (
            "Refund request handled end to end",
            (
                "gmail.threads_get > stripe.customers_list > stripe.charges_list > "
                "stripe.refunds_create > gmail.drafts_create"
            ),
            (
                "The charge is found, the refund issued and the reply drafted, with a "
                "human approving the refund."
            ),
            "per request",
        ),
        (
            "NPS detractor follow-up",
            (
                "gforms.forms_responses_list > stripe.customers_list > "
                "gmail.drafts_create > linear.customer_need_create"
            ),
            ("Low scores from paying accounts get a personal reply and their complaint tracked."),
            "weekly",
        ),
        (
            "Help-center gap finder",
            "gmail.threads_list > notion.search > notion.pages_create",
            "Questions asked three times with no article get a draft article.",
            "weekly",
        ),
        (
            "Escalation runbook",
            (
                "slack.conversations_history > linear.issue_update > "
                "gcalendar.events_insert > gmail.drafts_create"
            ),
            ("Priority raised, call booked, customer told: one command instead of four tabs."),
            "per event",
        ),
        (
            "Internal Q&A from the docs",
            (
                "slack.conversations_history > notion.search > gdrive.files_list > "
                "slack.chat_post_message"
            ),
            ("Questions in #ask get answered in-thread from the wiki and Drive, with links."),
            "hourly",
        ),
        (
            "Account health sheet",
            (
                "stripe.subscriptions_list > stripe.invoices_list > "
                "linear.issues_list > gsheets.spreadsheets_values_update"
            ),
            ("Billing state and open bugs per account in one sheet the CS team sorts by."),
            "daily",
        ),
    ),
    "finance": (
        (
            "Freelancer invoice from the week's work",
            (
                "gcalendar.events_list > github.search_commits > "
                "stripe.invoice_items_create > stripe.invoices_create > "
                "stripe.invoices_send"
            ),
            "Client meetings and commits become line items and a sent invoice.",
            "weekly",
        ),
        (
            "Failed payment follow-up",
            (
                "stripe.invoices_list > stripe.customers_retrieve > "
                "gmail.drafts_create > slack.chat_post_message"
            ),
            "Past-due invoices get a human email and the account owner is told.",
            "daily",
        ),
        (
            "Revenue sheet",
            (
                "stripe.subscriptions_list > stripe.balance_transactions_list > "
                "gsheets.spreadsheets_values_append"
            ),
            ("MRR, new, churned and fees appended daily to the sheet finance already uses."),
            "daily",
        ),
        (
            "Payout reconciliation",
            (
                "stripe.payouts_list > stripe.balance_transactions_list > "
                "gsheets.spreadsheets_values_update"
            ),
            "Each payout broken into the charges, refunds and fees inside it.",
            "weekly",
        ),
        (
            "Dispute evidence pack",
            (
                "stripe.disputes_list > stripe.disputes_retrieve > "
                "gmail.threads_list > shopify.order_get > stripe.disputes_update"
            ),
            ("Correspondence and fulfillment proof assembled and submitted before the deadline."),
            "per dispute",
        ),
        (
            "Receipts → Drive and the expense sheet",
            (
                "gmail.messages_list > gmail.messages_attachments_get > "
                "gdrive.files_create > gsheets.spreadsheets_values_append"
            ),
            "Every receipt filed and logged without forwarding emails to anyone.",
            "weekly",
        ),
        (
            "Vendor invoice inbox → approval",
            (
                "gmail.messages_list > gmail.messages_attachments_get > "
                "gdrive.files_create > gsheets.spreadsheets_values_append > "
                "slack.chat_post_message"
            ),
            ("Bills land in a sheet with the PDF and an approval request to the budget owner."),
            "daily",
        ),
        (
            "Plan change by email",
            (
                "gmail.threads_get > stripe.customers_list > "
                "stripe.subscriptions_update > gmail.drafts_create"
            ),
            ("'Please move us to annual' handled from the email, with confirmation drafted."),
            "per request",
        ),
        (
            "Investor update draft",
            (
                "stripe.balance_retrieve > stripe.subscriptions_list > "
                "linear.projects_list > gdocs.documents_create > gmail.drafts_create"
            ),
            "Numbers from billing and progress from the tracker, in your template.",
            "monthly",
        ),
        (
            "Price change rollout",
            (
                "stripe.prices_create > stripe.subscriptions_list > "
                "gmail.drafts_create > notion.pages_create"
            ),
            ("New price created, affected customers listed and notice drafted, with an FAQ page."),
            "on demand",
        ),
        (
            "Platform fee report",
            (
                "stripe.accounts_list > stripe.application_fees_list > "
                "gsheets.spreadsheets_values_update"
            ),
            "Fees per connected account per month, for marketplaces on Connect.",
            "monthly",
        ),
        (
            "SaaS spend audit",
            (
                "gmail.messages_list > gsheets.spreadsheets_values_append > "
                "slack.users_list > slack.chat_post_message"
            ),
            ("Every recurring vendor charge in the inbox, with an owner asked to justify it."),
            "quarterly",
        ),
        (
            "Bulk refunds from a sheet",
            (
                "gsheets.spreadsheets_values_get > stripe.charges_list > "
                "stripe.refunds_create > gsheets.spreadsheets_values_update"
            ),
            ("A list of affected orders after an incident, refunded and marked row by row."),
            "on demand",
        ),
        (
            "Price list from a sheet",
            ("gsheets.spreadsheets_values_get > stripe.products_create > stripe.prices_create"),
            "The pricing sheet the team agreed on becomes the products Stripe sells.",
            "on demand",
        ),
    ),
    "commerce": (
        (
            "Low stock → supplier PO draft",
            (
                "shopify.products_list > shopify.variant_inventory_level > "
                "gsheets.spreadsheets_values_append > gmail.drafts_create"
            ),
            "Reorders drafted before a bestseller goes out of stock.",
            "daily",
        ),
        (
            "Daily sales digest",
            ("shopify.orders_list > gsheets.spreadsheets_values_append > slack.chat_post_message"),
            "Yesterday's orders, revenue and top products, posted and logged.",
            "daily",
        ),
        (
            "Where-is-my-order replies",
            (
                "gmail.threads_list > shopify.orders_list > "
                "shopify.order_fulfillment_orders > gmail.drafts_create"
            ),
            "The commonest support email answered with the actual fulfillment status.",
            "hourly",
        ),
        (
            "Competitor product price watch",
            (
                "firecrawl.monitor_create > firecrawl.extract > shopify.product_get > "
                "slack.chat_post_message"
            ),
            "A competitor undercuts a SKU and you see both prices side by side.",
            "daily",
        ),
        (
            "Supplier sheet → new products",
            (
                "gsheets.spreadsheets_values_get > shopify.product_create > "
                "shopify.product_variants_bulk_create > slack.chat_post_message"
            ),
            "A season's catalogue goes from spreadsheet to store draft in one run.",
            "per season",
        ),
        (
            "Product copy from the supplier's page",
            "firecrawl.scrape > shopify.product_update",
            ("Specs and materials pulled from the manufacturer, written as your listing."),
            "on demand",
        ),
        (
            "Wholesale order by email → draft order",
            (
                "gmail.threads_get > shopify.customers_list > "
                "shopify.draft_order_create > gmail.drafts_create"
            ),
            "B2B buyers email a list and get an invoice link back.",
            "per request",
        ),
        (
            "Cancellation request handled",
            ("gmail.threads_get > shopify.order_get > shopify.order_cancel > gmail.drafts_create"),
            "Unfulfilled orders cancelled on request with the confirmation drafted.",
            "per request",
        ),
        (
            "VIP customer outreach",
            ("shopify.customers_list > gsheets.spreadsheets_values_update > gmail.drafts_create"),
            "Top spenders get a personal note before a launch, not a blast.",
            "per launch",
        ),
        (
            "Fulfillment exceptions",
            (
                "shopify.orders_list > shopify.order_fulfillment_orders > "
                "linear.issue_create > slack.chat_post_message"
            ),
            ("Orders unfulfilled after 48 hours become an ops issue with the order attached."),
            "daily",
        ),
        (
            "Stock count from a sheet",
            (
                "gsheets.spreadsheets_values_get > shopify.locations_list > "
                "shopify.inventory_adjust_quantities"
            ),
            ("The warehouse's count becomes the store's inventory without manual edits."),
            "weekly",
        ),
        (
            "Shopify + Stripe revenue in one sheet",
            (
                "shopify.orders_list > stripe.balance_transactions_list > "
                "gsheets.spreadsheets_values_append"
            ),
            "Stores selling in two places see one revenue number.",
            "daily",
        ),
    ),
    "ops": (
        (
            "Morning brief",
            (
                "gcalendar.events_list > gmail.threads_list > linear.issues_list > "
                "slack.chat_post_message"
            ),
            ("Today's meetings, emails that need you and issues due, in one message at 8am."),
            "daily",
        ),
        (
            "Meeting prep pack",
            (
                "gcalendar.events_get > gmail.threads_list > granola.notes_list > "
                "granola.notes_get > gdocs.documents_create"
            ),
            "Last time you met them, what they emailed since and what you promised.",
            "per meeting",
        ),
        (
            "Action items → owners",
            (
                "granola.notes_get > linear.users_list > linear.issue_create > "
                "slack.chat_post_message"
            ),
            ("Everything someone said they'd do is an assigned issue before the next meeting."),
            "per meeting",
        ),
        (
            "Internal weekly update",
            (
                "linear.project_updates_list > github.releases_list > "
                "stripe.subscriptions_list > gdocs.documents_create > "
                "slack.chat_post_message"
            ),
            "Shipped, revenue, risks: drafted from the systems, edited by a human.",
            "weekly",
        ),
        (
            "Inbox triage into tasks and time blocks",
            (
                "gmail.threads_list > gmail.threads_modify > linear.issue_create > "
                "gcalendar.events_quick_add"
            ),
            "Emails that are really tasks become issues with time held to do them.",
            "daily",
        ),
        (
            "Email → calendar",
            "gmail.threads_get > gcalendar.events_insert > gmail.drafts_create",
            "'Does Thursday 3pm work?' becomes an invite and a confirmation.",
            "per request",
        ),
        (
            "Meetings → Doc",
            "gcalendar.events_list > gcalendar.events_get > gdocs.documents_create",
            ("A week of meetings summarised into a doc for the people who weren't there."),
            "weekly",
        ),
        (
            "Decision log",
            ("slack.conversations_history > notion.data_sources_query > notion.pages_create"),
            "Decisions made in channels get recorded with who, when and why.",
            "daily",
        ),
        (
            "Offsite planning",
            (
                "gforms.forms_create > gforms.forms_responses_list > "
                "gcalendar.events_insert > gdocs.documents_create > "
                "slack.chat_post_message"
            ),
            "Dates, dietary needs and the agenda gathered and published.",
            "per event",
        ),
        (
            "OKR tracker",
            (
                "linear.initiatives_list > linear.initiative_get > "
                "gsheets.spreadsheets_values_update > linear.initiative_update_create"
            ),
            "Initiative progress rolled up to the sheet and posted as an update.",
            "weekly",
        ),
        (
            "Fundraising data room",
            (
                "gdrive.files_list > gdrive.files_copy > stripe.subscriptions_list > "
                "gsheets.spreadsheets_create > gdrive.permissions_create"
            ),
            "Folder assembled, revenue exported and access granted per investor.",
            "on demand",
        ),
        (
            "Unresolved doc comments → nudges",
            (
                "gdrive.files_list > gdrive.comments_list > slack.users_list > "
                "slack.chat_post_message"
            ),
            "Comments that have waited three days get their owner pinged.",
            "daily",
        ),
        (
            "Contract renewal calendar",
            (
                "gdrive.files_list > gdocs.documents_get > gcalendar.events_insert > "
                "slack.chat_post_message"
            ),
            "Every contract's notice date is on a calendar 60 days ahead.",
            "monthly",
        ),
        (
            "Offboarding access sweep",
            (
                "gdrive.permissions_list > gdrive.permissions_delete > "
                "linear.team_membership_delete > slack.chat_post_message"
            ),
            "Files shared with someone who left get revoked, with a report.",
            "per event",
        ),
        (
            "Sheet → calendar",
            (
                "gsheets.spreadsheets_values_get > gcalendar.events_insert > "
                "gsheets.spreadsheets_values_update"
            ),
            "A schedule kept in a sheet becomes real events, with IDs written back.",
            "on demand",
        ),
        (
            "Inbox → sheet",
            ("gmail.messages_list > gmail.messages_get > gsheets.spreadsheets_values_append"),
            "Orders, signups or applications that arrive by email become rows.",
            "daily",
        ),
        (
            "Drive folder → Notion",
            (
                "gdrive.files_list > gdrive.files_export > notion.pages_create > "
                "notion.pages_update_markdown"
            ),
            "A migration that usually takes a week of copy-paste.",
            "on demand",
        ),
        (
            "Granola → Notion meeting database",
            (
                "granola.notes_list > granola.notes_get > notion.data_sources_query > "
                "notion.pages_create"
            ),
            ("Every meeting note in the team's Notion with attendees and decisions as properties."),
            "daily",
        ),
        (
            "Notion tasks ↔ Linear",
            "notion.data_sources_query > linear.issue_create > notion.pages_update",
            "Non-engineers file in Notion and see the Linear status reflected back.",
            "hourly",
        ),
        (
            "Spreadsheet backlog → Linear",
            (
                "gsheets.spreadsheets_values_get > linear.search_issues > "
                "linear.issue_create > gsheets.spreadsheets_values_update"
            ),
            "The backlog someone kept in a sheet moves to Linear, IDs written back.",
            "on demand",
        ),
    ),
    "research": (
        (
            "Competitive intel digest",
            (
                "firecrawl.monitor_checks_list > tavily.search > notion.pages_create > "
                "slack.chat_post_message"
            ),
            "Site changes and news per competitor, weekly, in one page.",
            "weekly",
        ),
        (
            "Deep research → shared doc",
            (
                "tavily.research_create > tavily.research_get > "
                "gdocs.documents_create > slack.chat_post_message"
            ),
            "A cited report in the team's Drive, not in someone's chat history.",
            "on demand",
        ),
        (
            "Paper watch",
            (
                "firecrawl.research_papers_search > firecrawl.research_paper_get > "
                "notion.pages_create > slack.chat_post_message"
            ),
            "New papers on your topics land in a reading list with abstracts.",
            "weekly",
        ),
        (
            "Market map",
            "tavily.search > firecrawl.extract > gsheets.spreadsheets_values_update",
            "Players, pricing, funding and positioning, one row each.",
            "on demand",
        ),
        (
            "Pricing benchmark memo",
            ("firecrawl.extract > gsheets.spreadsheets_values_update > gdocs.documents_create"),
            ("Ten competitors' pricing pages normalised into one table and a recommendation."),
            "on demand",
        ),
        (
            "Regulatory watch",
            (
                "firecrawl.monitor_create > firecrawl.monitor_checks_list > "
                "notion.pages_create > slack.chat_post_message"
            ),
            "A regulator's guidance page changes and legal hears the same day.",
            "daily",
        ),
        (
            "Company due diligence",
            (
                "tavily.research_create > github.search_repositories > "
                "firecrawl.crawl > gdocs.documents_create"
            ),
            "Public footprint, open-source activity and product surface in one memo.",
            "on demand",
        ),
        (
            "Public complaints → roadmap evidence",
            (
                "tavily.search > firecrawl.scrape > notion.pages_create > "
                "linear.customer_need_create"
            ),
            ("What people complain about in your category, attached to the issues it supports."),
            "monthly",
        ),
        (
            "Open-source landscape",
            (
                "github.search_repositories > github.repos_list_languages > "
                "tavily.search > notion.pages_create"
            ),
            "Who is building what in your space, with momentum, before you build it.",
            "monthly",
        ),
        (
            "Web page → Linear issue",
            "firecrawl.scrape > linear.search_issues > linear.issue_create",
            "A public bug report, forum post or status page becomes a tracked issue.",
            "on demand",
        ),
    ),
    "people": (
        (
            "Applications inbox → candidate sheet",
            (
                "gmail.threads_list > gmail.messages_attachments_get > "
                "gdrive.files_create > gsheets.spreadsheets_values_append"
            ),
            ("Every application filed with its CV and a row, no ATS needed at ten hires a year."),
            "daily",
        ),
        (
            "Interview scheduling",
            (
                "gsheets.spreadsheets_values_get > gcalendar.events_list > "
                "gcalendar.events_insert > gmail.messages_send"
            ),
            "Panels booked around everyone's calendars with the candidate confirmed.",
            "per candidate",
        ),
        (
            "Interview debrief",
            "granola.notes_get > notion.pages_update > slack.chat_post_message",
            (
                "Each interviewer's notes summarised onto the candidate page, posted to "
                "the hiring channel."
            ),
            "per interview",
        ),
        (
            "Engineering candidate's public work",
            (
                "github.search_repositories > github.repos_list_languages > "
                "github.search_commits > notion.pages_update"
            ),
            "What they've built in public, summarised before the technical interview.",
            "per candidate",
        ),
        (
            "New hire day one",
            (
                "gcalendar.events_insert > slack.conversations_invite > "
                "linear.team_membership_create > gdrive.permissions_create > "
                "notion.pages_create"
            ),
            (
                "Week-one meetings, channels, team, folders and checklist, from one name "
                "and start date."
            ),
            "per hire",
        ),
        (
            "Pulse survey",
            (
                "gforms.forms_create > slack.chat_post_message > "
                "gforms.forms_responses_list > gdocs.documents_create"
            ),
            "Survey sent where people are, results summarised for leadership.",
            "monthly",
        ),
        (
            "Offer letter",
            (
                "notion.pages_retrieve > gdrive.files_copy > "
                "gdocs.documents_batch_update > gmail.drafts_create"
            ),
            "Template copied, filled from the candidate page and drafted to send.",
            "per hire",
        ),
        (
            "Job post from the market",
            "tavily.search > firecrawl.scrape > gdocs.documents_create",
            ("A job description benchmarked against how others describe and pay the role."),
            "per role",
        ),
    ),
    "agency": (
        (
            "Client onboarding",
            (
                "stripe.customers_create > stripe.checkout_sessions_create > "
                "gdrive.files_copy > gdrive.permissions_create > linear.project_create"
            ),
            ("Deposit link, SOW from template, shared folder and project, for each new client."),
            "per client",
        ),
        (
            "Deposit paid → kickoff",
            (
                "stripe.checkout_sessions_list > gcalendar.events_insert > "
                "linear.project_create > gmail.messages_send"
            ),
            "The kickoff is booked the moment the deposit clears.",
            "hourly",
        ),
        (
            "Client status report",
            (
                "linear.project_get > linear.issues_list > github.repos_list_commits > "
                "gdocs.documents_create > gmail.drafts_create"
            ),
            "A weekly report the client can read, built from the work itself.",
            "weekly",
        ),
        (
            "Scope creep detector",
            ("granola.notes_get > gdocs.documents_get > linear.issues_list > gmail.drafts_create"),
            ("Asks on the call that aren't in the SOW get flagged and a change order drafted."),
            "per call",
        ),
        (
            "Billable hours from calendar",
            (
                "gcalendar.events_list > gsheets.spreadsheets_values_append > "
                "stripe.invoice_items_create"
            ),
            "Client-tagged meetings become a timesheet and pending line items.",
            "weekly",
        ),
        (
            "Overdue invoice chaser",
            (
                "stripe.invoices_list > gmail.threads_list > gmail.drafts_create > "
                "gcalendar.events_quick_add"
            ),
            (
                "Escalating reminders that cite the last thread, and a follow-up held on "
                "your calendar."
            ),
            "weekly",
        ),
        (
            "Client site audit → proposal",
            (
                "firecrawl.crawl > firecrawl.crawl_status > gdocs.documents_create > "
                "stripe.checkout_sessions_create"
            ),
            ("A prospect's site audited and turned into a scoped proposal with a pay link."),
            "on demand",
        ),
        (
            "Client feedback in Drive comments → tasks",
            "gdrive.comments_list > linear.issue_create > gdrive.replies_create",
            (
                "Every comment the client left on a deliverable becomes a task, and they "
                "see the link."
            ),
            "daily",
        ),
    ),
}
