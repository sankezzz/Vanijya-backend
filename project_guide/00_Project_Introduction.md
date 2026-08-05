# 00 — Project Introduction

> **Read this first.** Everything else in this handbook assumes you've read this page.

## Who this handbook is for

You are a backend engineer who just joined this project. You have never seen this repository before. Nobody from the original team is available to explain it to you. This handbook is meant to be a complete substitute for that missing onboarding conversation.

You don't need to already know FastAPI, SQLAlchemy, Redis, PostgreSQL, dependency injection, the repository pattern, or how recommendation systems work. Every one of those concepts is explained the first time it matters, in plain language, before it's used to explain anything else. If you already know some of them, skip ahead freely — nothing later assumes you read the explanation, it's there for the reader who needs it.

## What is Vanijyaa?

**Vanijyaa is a business networking and trading platform for the agricultural commodity trade** — think of it as a mix of a professional social network (like LinkedIn) and a classifieds/deal board, built specifically for people who buy and sell commodities like rice, cotton, and sugar.

The people who use it fall into three roles, which the system treats as first-class concepts throughout:

- **Trader** — buys and sells commodities directly.
- **Broker** — connects buyers and sellers, doesn't necessarily hold stock.
- **Exporter** — moves commodities across borders, subject to export-specific rules (e.g. IEC — Import Export Code — verification, see [Authentication](14_Authentication.md)).

A user picks one of these roles during onboarding, and it shapes what they see: which posts are relevant, which groups get suggested, which other users the recommendation engine surfaces, and even which KYB (business-verification) documents they're asked for.

The platform gives these users:
- A **feed** of posts — market updates, requirements/deals, discussions, and general knowledge-sharing (see [Feature Guide](10_Feature_Guide.md)).
- A **connections** system — follow other traders/brokers/exporters, get matched with relevant ones via a recommendation engine, send message requests.
- **Groups** — topic- or region-based communities (e.g. "Maharashtra Rice Traders") with their own chat, deals, and membership rules.
- **Direct and group chat**, including the ability to share a "deal card" (structured buy/sell listing) directly inside a conversation.
- A **news feed** — curated, AI-enriched agricultural/trade news, personalized by role and by what commodities/regions the user cares about.
- **Verification** — KYC (identity: PAN, eventually Aadhaar) and KYB (business: GST, IEC) checks against third-party government-data APIs, unlocking "verified" badges.
- **Safety tooling** — block and report other users.

If you want the full tour of what each of these does from a user's point of view before diving into code, read [Product Overview](01_Product_Overview.md) next.

## Why this handbook exists

This codebase was built incrementally, across many sessions, by (per the git history and the prior audit) what appears to be primarily one or two developers iterating quickly — building a feature, then rebuilding parts of it better, sometimes without removing the earlier version. That's a completely normal way for a real product to get built, but it means **reading the code in isolation, file by file, will sometimes mislead you** — you might land on a first-draft implementation that looks plausible but is no longer used, or an in-progress feature that looks complete but is only half-wired.

A full architectural audit was already performed on this exact codebase (see `audit/audit_phase_14_FINAL_REPORT.md`) specifically to find those traps: dead code, duplicated logic, disconnected features, stale documentation. This handbook uses that audit as a cross-reference — wherever something in the code turns out to be dead, duplicated, or broken in a way the audit already diagnosed, this handbook says so plainly and links to the finding — but **this handbook is not the audit**. The audit's job was to critique. This handbook's job is to teach you how the system actually works today, warts included, so you can be productive immediately: read code confidently, trace a request through the system, find the right file to change, and know which parts of the app to trust versus double-check.

## How to use this handbook

The 32 documents are numbered in a reading order that builds understanding progressively — each one assumes you've read the ones before it:

- **00–04** (this section): the big picture — what the product is, how the system is shaped, how the repository is organized.
- **05–08**: runtime mechanics — what happens when the server starts, and what happens to one HTTP request from the moment it arrives to the moment a response goes out.
- **09**: the database — every table, every relationship.
- **10–13**: the application's structure — features, modules, the service layer, the (partial) repository layer.
- **14–23**: cross-cutting concerns, one topic per document — authentication, authorization, caching, Redis, background jobs, the recommendation engine, real-time events, image uploads, search, notifications.
- **24–26**: operating the system — configuration, error handling, deployment.
- **27–31**: reference material you'll come back to repeatedly — glossary, debugging playbook, FAQ, known limitations, and a reconstructed record of the big architectural decisions and why they were made.

You do not have to read this front-to-back in one sitting. Once you've read 00–08, the rest is designed to be referenced as needed — if you're about to touch the chat feature, go read [Modules](11_Modules.md)'s Chat section and [Event Flows](20_Event_Flows.md) before you start.

## What this project is built with, in one paragraph

The backend is a single Python web application built on **FastAPI** (a framework for building HTTP APIs), storing its data in **PostgreSQL** (a relational database) via **SQLAlchemy** (a library that lets Python code describe database tables as classes and query them without writing raw SQL by hand — called an "ORM," Object-Relational Mapper). Schema changes to the database are tracked with **Alembic**, a migration tool that keeps a versioned history of every table/column change so the database can be rebuilt from scratch or upgraded safely. **Redis** (a fast in-memory key-value store) is used for short-lived data — rate limiting, session-scoped personalization signals, caching. Real-time features (chat, live delivery/read receipts, typing indicators) run over **Socket.IO**, a protocol for persistent two-way connections between client and server, layered on top of the same FastAPI process. Recommendation and search-like matching features use **pgvector**, a PostgreSQL extension that lets the database store numeric "embedding" vectors and search by similarity — explained in full in [Recommendation Engine](19_Recommendation_Engine.md). Every one of these technologies is explained from scratch, the first time it becomes relevant to something you're reading about, in the relevant later document — you don't need to go learn them elsewhere first.

## A note on trust

Per this handbook's own ground rules (see `audits/PROGRESS.md`), every claim in these 32 documents is checked against the current code, not assumed from the audit, from `documentation/`, or from `upgraded_documentation/` — all three of which the audit found to contain material that no longer matches the running system. Where this handbook cites the audit, it's citing a *specific, already-verified finding*, not repeating an assumption. Where something couldn't be verified, it says so explicitly rather than guessing. You should extend the same skepticism forward in time: this handbook is accurate as of the commit it was written against — if you're reading it months later and something seems off, trust the code over the document, the same way this document trusts the code over everything written before it.

---
**Next:** [01 — Product Overview](01_Product_Overview.md)
