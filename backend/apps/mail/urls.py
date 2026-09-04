from django.urls import path
from .views import (
    MailboxListView, MessageListView, MessageDetailView, ThreadDetailView,
    MessageActionView, BulkActionView, AttachmentView,
    SendView, DraftView, SearchView
)

urlpatterns = [
    path("mailboxes/", MailboxListView.as_view(), name="mailboxes"),
    path("mailboxes/<path:mailbox>/messages/", MessageListView.as_view(), name="message-list"),
    path("messages/bulk/", BulkActionView.as_view(), name="bulk-action"),
    path("messages/<path:mailbox>/<str:uid>/attachments/", AttachmentView.as_view(), name="attachment"),
    path("messages/<path:mailbox>/<str:uid>/<str:action>/", MessageActionView.as_view(), name="message-action"),
    path("threads/<path:mailbox>/<str:uid>/", ThreadDetailView.as_view(), name="thread-detail"),
    path("messages/<path:mailbox>/<str:uid>/", MessageDetailView.as_view(), name="message-detail"),
    path("search/", SearchView.as_view(), name="search"),
    path("send/", SendView.as_view(), name="send"),
    path("drafts/", DraftView.as_view(), name="drafts"),
]
