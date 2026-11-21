package com.molido.agroai

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
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
        composeRule.onNodeWithText("برای نگهداری اطلاعات خصوصی، ابتدا وارد حساب شوید.").assertIsDisplayed()
    }
}
