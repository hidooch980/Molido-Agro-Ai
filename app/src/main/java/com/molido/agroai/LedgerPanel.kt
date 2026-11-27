package com.molido.agroai

import android.content.Context
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.molido.agroai.data.AccountRole
import com.molido.agroai.data.LedgerApi
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

private val LedgerPanelColor = Color(0xFF1B2C23)
private val LedgerMuted = Color(0xFFB8C8BE)
private val LedgerPositive = Color(0xFF9BE0B1)
private val LedgerWarning = Color(0xFFF0C36D)

/**
 * Approval queue and posted totals. Postings are created by the server (inventory, orders,
 * settlements), so this panel only reads the queue and confirms one entry at a time with the
 * shared approval token, which acts as the second signature.
 */
@Composable
fun LedgerPanel(context: Context, role: AccountRole?) {
    val scope = rememberCoroutineScope()
    var pending by remember { mutableStateOf<List<LedgerApi.Journal>>(emptyList()) }
    var report by remember { mutableStateOf<LedgerApi.Report?>(null) }
    var approvalToken by remember { mutableStateOf("") }
    var status by remember { mutableStateOf("برای دیدن اسناد در انتظار تأیید، به سرور وصل شوید.") }
    var busy by remember { mutableStateOf(false) }
    var reload by remember { mutableIntStateOf(0) }

    LaunchedEffect(role, reload) {
        busy = true
        val loaded = withContext(Dispatchers.IO) {
            runCatching { LedgerApi.pending(context) to LedgerApi.report(context) }
        }
        loaded.fold(
            { (queue, summary) ->
                pending = queue
                report = summary
                status = when {
                    queue.isEmpty() -> "سندی در انتظار تأیید نیست."
                    else -> "${queue.size} سند در انتظار تأیید است."
                }
            },
            { pending = emptyList(); report = null; status = it.message ?: "دریافت اسناد ناموفق بود." },
        )
        busy = false
    }

    Card(
        colors = CardDefaults.cardColors(containerColor = LedgerPanelColor),
        shape = RoundedCornerShape(16.dp),
        modifier = Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 6.dp),
    ) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("تأیید اسناد مالی", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Text(status, color = LedgerMuted, style = MaterialTheme.typography.bodySmall)

            val approver = role?.canApproveFinances == true
            if (!approver) {
                Text(
                    "این حساب اجازه تأیید سند مالی ندارد؛ تأیید را سرپرست یا حسابدار انجام می‌دهد.",
                    color = LedgerWarning,
                    style = MaterialTheme.typography.bodySmall,
                )
            }

            if (pending.isNotEmpty()) {
                OutlinedTextField(
                    value = approvalToken,
                    onValueChange = { approvalToken = it },
                    label = { Text("توکن تأیید (X-Approval-Token)") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
            }

            pending.forEach { journal ->
                Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                    Text(
                        "${journal.description} • ${formatAmount(journal.totalDebit)} ${journal.currency}",
                        style = MaterialTheme.typography.bodyMedium,
                        fontWeight = FontWeight.SemiBold,
                    )
                    journal.lines.forEach { line ->
                        Text(
                            "${line.accountCode} — بدهکار ${formatAmount(line.debit)} / بستانکار ${formatAmount(line.credit)}",
                            color = LedgerMuted,
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                    Button(
                        enabled = !busy && approver,
                        onClick = {
                            busy = true
                            scope.launch {
                                val result = withContext(Dispatchers.IO) {
                                    runCatching { LedgerApi.approve(context, journal.id, approvalToken.trim()) }
                                }
                                status = result.fold(
                                    { "سند تأیید و ثبت شد ($it)." },
                                    { it.message ?: "تأیید سند ناموفق بود." },
                                )
                                reload += 1
                            }
                        },
                    ) { Text("تأیید و ثبت سند") }
                }
            }

            report?.let { summary ->
                if (summary.accounts.isNotEmpty()) {
                    Text(
                        "تراز اسناد ثبت‌شده (${summary.journalCount} سند)",
                        style = MaterialTheme.typography.bodyMedium,
                        fontWeight = FontWeight.SemiBold,
                        modifier = Modifier.padding(top = 4.dp),
                    )
                    summary.accounts
                        .filter { it.debit != 0.0 || it.credit != 0.0 }
                        .forEach { account ->
                            Text(
                                "${account.code} ${account.name}: بدهکار ${formatAmount(account.debit)} / بستانکار ${formatAmount(account.credit)}",
                                color = LedgerPositive,
                                style = MaterialTheme.typography.bodySmall,
                            )
                        }
                }
            }

            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(enabled = !busy, onClick = { reload += 1 }) { Text("نوسازی") }
            }
        }
    }
}

private fun formatAmount(value: Double): String =
    if (value == value.toLong().toDouble()) value.toLong().toString() else String.format("%.2f", value)