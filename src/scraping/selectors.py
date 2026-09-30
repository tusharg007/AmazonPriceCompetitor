"""Named selector groups. Locale variants are explicit rather than guessed at call sites."""

from __future__ import annotations

PRODUCT_READY = ("#productTitle", "#dp", "#centerCol")
SEARCH_READY = ("div[data-component-type='s-search-result']", "[data-asin][data-component-type]")
BLOCK_MARKERS = (
    "#captchacharacters",
    "form[action*='validateCaptcha']",
    "#authportal-main-section",
)
NOT_FOUND_MARKERS = ("#g", "#cs_404", "#error-page")
TITLE = ("#productTitle", "#title span")
PRICE = (
    "#corePriceDisplay_desktop_feature_div .a-priceToPay .a-offscreen",
    "#corePrice_feature_div .a-price .a-offscreen",
    "#apex_desktop .a-price .a-offscreen",
    ".reinventPricePriceToPayMargin .a-offscreen",
    "#priceblock_ourprice",
    "#priceblock_dealprice",
    "#corePriceDisplay_desktop_feature_div .a-priceToPay",
    "#corePrice_feature_div .a-price",
)
BRAND = ("#bylineInfo", "#productOverview_feature_div tr th")
RATING = ("#acrPopover", "i[data-hook='average-star-rating'] span")
RATING_COUNT = ("#acrCustomerReviewText", "span[data-hook='total-review-count']")
AVAILABILITY = ("#availability span", "#outOfStock")
IMAGE = ("#landingImage", "#imgTagWrapperId img")
BREADCRUMBS = (
    "#wayfinding-breadcrumbs_feature_div ul li a",
    "#wayfinding-breadcrumbs_container ul li a",
)
LOCATION_TRIGGER = ("#glow-ingress-line2", "#nav-global-location-popover-link")
LOCATION_INPUT = ("#GLUXZipUpdateInput", "input[name='location']")
LOCATION_APPLY = ("#GLUXZipUpdate .a-button-input", "#GLUXZipUpdate-announce")
LOCATION_DISPLAY = ("#glow-ingress-line2", "#nav-global-location-slot")
SEARCH_CARD = "div[data-component-type='s-search-result'][data-asin]"
SEARCH_TITLE = ("h2 a span", "h2 span")
SEARCH_LINK = "h2 a"
NEXT_PAGE = ("a.s-pagination-next", "a[aria-label*='Next']")
