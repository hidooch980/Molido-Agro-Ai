package com.molido.agroai

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createAndroidComposeRule
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
        composeRule.onNodeWithText("نام کاربری باید ۳ تا ۶۴ نویسه", substring = true).assertIsDisplayed()
    }

    @Test
    fun crmErpWorkspaceIsAvailableInPersianNavigation() {
        composeRule.onNodeWithText("CRM/ERP").performClick()
        composeRule.onNodeWithText("مدیریت مشتری و کسب‌وکار").assertIsDisplayed()
        composeRule.onNodeWithText("حالت محلی بدون حساب فعال است", substring = true).assertIsDisplayed()
        composeRule.onNodeWithText("ثبت مشتری").assertIsDisplayed()
    }

    @Test
    fun crmErpSavesEncryptedCustomerLocallyWithoutAccount() {
        composeRule.onNodeWithText("CRM/ERP").performClick()
        composeRule.onNodeWithText("نام مشتری").performScrollTo().performTextInput("مشتری محلی آزمایشی")
        composeRule.onNodeWithText("ثبت مشتری").performScrollTo().performClick()
        composeRule.onNodeWithText("اطلاعات رمزگذاری‌شده فقط روی این دستگاه ذخیره شد", substring = true).assertIsDisplayed()
    }

    @Test
    fun legacyBusinessRecordsRemainReachable() {
        composeRule.onNodeWithText("CRM/ERP").performClick()
        composeRule.onNodeWithText("سوابق عمومی قدیمی").performClick()
        composeRule.onNodeWithText("مدیریت یکپارچه CRM و ERP").assertIsDisplayed()
        composeRule.onNodeWithText("ذخیره محلی و افزودن به صف همگام‌سازی").assertIsDisplayed()
    }
}
