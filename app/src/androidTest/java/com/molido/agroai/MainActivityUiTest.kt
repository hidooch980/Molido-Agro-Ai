package com.molido.agroai

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
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
        composeRule.onNodeWithText("نام مشتری").performScrollTo().performTextInput("مشتری محلی آزمایشی")
        composeRule.onNodeWithText("ثبت مشتری").performScrollTo().performClick()
        val successNotice = "اطلاعات رمزگذاری‌شده فقط روی این دستگاه ذخیره شد"
        val failureNotice = "ذخیره اطلاعات ناموفق بود"
        // Local persistence runs in a coroutine; wait for its observable result rather than
        // asserting before Room/Keystore work has completed.
        composeRule.waitUntil(timeoutMillis = 10_000) {
            composeRule.onAllNodesWithText(successNotice, substring = true)
                .fetchSemanticsNodes().isNotEmpty() ||
                composeRule.onAllNodesWithText(failureNotice, substring = true)
                    .fetchSemanticsNodes().isNotEmpty()
        }
        composeRule.onNodeWithText(successNotice, substring = true)
            .performScrollTo().assertIsDisplayed()
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
