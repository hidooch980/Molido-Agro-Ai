package com.molido.agroai

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.printToString
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class MainActivityUiTest {
    @get:Rule
    val composeRule = createAndroidComposeRule<MainActivity>()

    @Test
    fun dashboardAndNavigationRenderInPersian() {
        composeRule.onNodeWithText("مولیدو آگرو").assertIsDisplayed()
        composeRule.onNodeWithText("خانه").assertIsDisplayed()
        composeRule.onNodeWithText("گلخانه").assertIsDisplayed()
        composeRule.onNodeWithText("مدیریت هوشمند کشاورزی و گلخانه").assertIsDisplayed()
    }

    @Test
    fun createAccountButtonShowsValidationInsteadOfAppearingUnresponsive() {
        composeRule.onNodeWithText("ساخت حساب").performScrollTo().performClick()
        composeRule.onNodeWithText("نام کاربری باید ۳ تا ۶۴ نویسه", substring = true)
            .performScrollTo().assertIsDisplayed()
    }

    @Test
    fun crmErpWorkspaceIsAvailableInPersianNavigation() {
        composeRule.onNodeWithText("CRM/ERP").performClick()
        composeRule.onNodeWithText("مدیریت مشتری و کسب‌وکار").performScrollTo().assertIsDisplayed()
        composeRule.onNodeWithText("حالت محلی بدون حساب فعال است", substring = true)
            .performScrollTo().assertIsDisplayed()
        composeRule.onNodeWithText("ثبت مشتری").performScrollTo().assertIsDisplayed()
    }

    @Test
    fun crmErpSavesEncryptedCustomerLocallyWithoutAccount() {
        composeRule.onNodeWithText("CRM/ERP").performClick()
        composeRule.waitForIdle()
        composeRule.onNodeWithText("نام مشتری").performScrollTo().performTextInput("مشتری محلی آزمایشی")
        // A dropped keystroke would otherwise surface only as a timeout; catch it at the source.
        composeRule.onNodeWithText("مشتری محلی آزمایشی").assertExists()
        composeRule.onNodeWithText("ثبت مشتری").performScrollTo().performClick()
        // The save runs on a background dispatcher, the Keystore hands out the AES key on first use
        // and the record list reflows when the row lands. A cold software-rendered emulator can spend
        // most of a minute on that first write, so wait for any outcome instead of racing one frame:
        // a refusal or a validation message is a real answer and gets reported with the screen below.
        val saved = "اطلاعات رمزگذاری‌شده فقط روی این دستگاه ذخیره شد"
        val outcomes = listOf(saved, "ذخیره اطلاعات ناموفق بود", "نام مشتری را وارد کنید.")
        fun noticeVisible(text: String) =
            composeRule.onAllNodesWithText(text, substring = true).fetchSemanticsNodes().isNotEmpty()
        composeRule.waitUntil(timeoutMillis = 90_000) { outcomes.any(::noticeVisible) }
        assertTrue(
            "ثبت مشتری نتیجه نداد؛ وضعیت صفحه:" + System.lineSeparator() + composeRule.onRoot().printToString(),
            noticeVisible(saved)
        )
        composeRule.onNodeWithText(saved, substring = true).performScrollTo().assertIsDisplayed()
    }

    @Test
    fun legacyBusinessRecordsRemainReachable() {
        composeRule.onNodeWithText("CRM/ERP").performClick()
        composeRule.onNodeWithText("سوابق عمومی قدیمی").performScrollTo().performClick()
        composeRule.onNodeWithText("مدیریت یکپارچه CRM و ERP").performScrollTo().assertIsDisplayed()
        composeRule.onNodeWithText("ذخیره محلی و افزودن به صف همگام‌سازی")
            .performScrollTo().assertIsDisplayed()
    }
}
