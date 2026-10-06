"""Declarative CSS selector chains for Amazon product and search pages."""

from __future__ import annotations

# Page ready markers
PRODUCT_READY = ("#productTitle", "#dp", "#centerCol")
SEARCH_READY = ("div[data-component-type='s-search-result']", "[data-asin][data-component-type]")

# Anti-bot and challenge detection
BLOCK_MARKERS = (
    "#captchacharacters",
    "form[action*='validateCaptcha']",
    "#authportal-main-section",
)
NOT_FOUND_MARKERS = ("#g", "#cs_404", "#error-page")

# Product detail page selectors
TITLE = ("#productTitle", "#title span", "h1#title")
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
BRAND = (
    "#bylineInfo",
    "#productOverview_feature_div tr:has(th:has-text('Brand')) td",
    "a#bylineInfo",
    "#brand",
)
RATING = (
    "#acrPopover span.a-icon-alt",
    "#acrPopover",
    "i[data-hook='average-star-rating'] span",
    "span[data-hook='rating-out-of-text']",
)
RATING_COUNT = (
    "#acrCustomerReviewText",
    "span[data-hook='total-review-count']",
)
AVAILABILITY = (
    "#availability span",
    "#outOfStock",
    "#availability",
)
IMAGE = (
    "#landingImage",
    "#imgTagWrapperId img",
    "#main-image",
)
BREADCRUMBS = (
    "#wayfinding-breadcrumbs_feature_div ul li a",
    "#wayfinding-breadcrumbs_container ul li a",
)

# Geographic postal code interaction
LOCATION_TRIGGER = ("#glow-ingress-line2", "#nav-global-location-popover-link")
LOCATION_INPUT = ("#GLUXZipUpdateInput", "input[name='location']")
LOCATION_APPLY = ("#GLUXZipUpdate .a-button-input", "#GLUXZipUpdate-announce")
LOCATION_DISPLAY = ("#glow-ingress-line2", "#nav-global-location-slot")

# Search results page selectors
SEARCH_CARD = "div[data-component-type='s-search-result'][data-asin]"
SEARCH_TITLE = ("h2 a span", "h2 span", "h2")
SEARCH_LINK = "h2 a, a:has(h2)"
SEARCH_PRICE = (
    ".a-price .a-offscreen",
    "span.a-price span.a-offscreen",
    ".a-color-base .a-price .a-offscreen",
)
SEARCH_RATING = ("i.a-icon-star-small span.a-icon-alt", "i.a-icon-star span.a-icon-alt")
SEARCH_RATING_COUNT = ("span[aria-label*='ratings']", ".a-size-small .a-link-normal")
SEARCH_IMAGE = "img.s-image"
NEXT_PAGE = ("a.s-pagination-next", "a[aria-label*='Next']")
