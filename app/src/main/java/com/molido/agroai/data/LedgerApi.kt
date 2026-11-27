package com.molido.agroai.data

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject

/**
 * Double-entry postings live on the server: they are written as PENDING_APPROVAL and only an
 * approver may confirm them. This client reads that queue and posts the decision, so the role
 * shown in the account panel is something the account can actually act on.
 */
object LedgerApi {
    data class Line(val accountCode: String, val debit: Double, val credit: Double, val description: String)

    data class Journal(
        val id: String,
        val description: String,
        val currency: String,
        val totalDebit: Double,
        val status: String,
        val lines: List<Line>,
    )

    data class AccountTotal(
        val code: String,
        val name: String,
        val type: String,
        val debit: Double,
        val credit: Double,
    )

    data class Report(val accounts: List<AccountTotal>, val journalCount: Int)

    suspend fun pending(context: Context): List<Journal> = withContext(Dispatchers.IO) {
        val body = ServerHttp.request(context, "GET", "/v1/erp/ledger/journals?status=PENDING_APPROVAL&limit=50")
        val items = JSONObject(body).optJSONArray("items") ?: return@withContext emptyList()
        buildList {
            for (index in 0 until items.length()) {
                val item = items.optJSONObject(index) ?: continue
                add(
                    Journal(
                        id = item.optString("id"),
                        description = item.optString("description"),
                        currency = item.optString("currency", "IRR"),
                        totalDebit = item.optDouble("totalDebit", 0.0),
                        status = item.optString("status", "PENDING_APPROVAL"),
                        lines = parseLines(item),
                    )
                )
            }
        }
    }

    suspend fun approve(context: Context, journalId: String, approvalToken: String): String = withContext(Dispatchers.IO) {
        require(journalId.isNotBlank()) { "سند انتخاب نشده است." }
        require(approvalToken.length >= 32) { "توکن تأیید باید حداقل ۳۲ نویسه باشد." }
        val body = ServerHttp.request(
            context, "POST", "/v1/erp/ledger/journals/$journalId/approve", "{}",
            mapOf("X-Approval-Token" to approvalToken),
        )
        JSONObject(body).optString("status", "POSTED")
    }

    suspend fun report(context: Context): Report = withContext(Dispatchers.IO) {
        val json = JSONObject(ServerHttp.request(context, "GET", "/v1/erp/reports/financial"))
        val accounts = json.optJSONArray("accounts")
        val rows = buildList {
            if (accounts != null) {
                for (index in 0 until accounts.length()) {
                    val row = accounts.optJSONObject(index) ?: continue
                    add(
                        AccountTotal(
                            code = row.optString("code"),
                            name = row.optString("name"),
                            type = row.optString("type"),
                            debit = row.optDouble("debit", 0.0),
                            credit = row.optDouble("credit", 0.0),
                        )
                    )
                }
            }
        }
        Report(accounts = rows, journalCount = json.optInt("journalCount", 0))
    }

    private fun parseLines(item: JSONObject): List<Line> {
        val lines = item.optJSONArray("lines") ?: return emptyList()
        return buildList {
            for (index in 0 until lines.length()) {
                val line = lines.optJSONObject(index) ?: continue
                add(
                    Line(
                        accountCode = line.optString("accountCode"),
                        debit = line.optDouble("debit", 0.0),
                        credit = line.optDouble("credit", 0.0),
                        description = line.optString("description"),
                    )
                )
            }
        }
    }
}