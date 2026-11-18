.pragma library

var STATUS_DONE = "logseq.property/status.done";
var STATUS_TODO = "logseq.property/status.todo";
var STATUS_CANCELED = "logseq.property/status.canceled";
var PAGE_LINK_SCHEME = "logseq-page:";

// Whether a task's status or priority is the given choice. Choices you add
// in Logseq have only an id; built-ins have an ident too.
function sameChoice(taskId, taskIdent, choice) {
    if (!choice)
        return false;
    if (choice.id !== null && choice.id !== undefined && taskId === choice.id)
        return true;
    return !!choice.ident && taskIdent === choice.ident;
}

// Icon for the sync marker (Breeze names, available in most icon themes).
function syncIcon(state) {
    switch (state) {
    case "cloud": return "state-ok";
    case "uploading":
    case "saving": return "state-sync";
    case "local": return "state-offline";
    case "local-only": return "drive-harddisk";
    case "failed": return "state-error";
    }
    return "state-information";
}

function isDone(status) {
    return status === STATUS_DONE;
}

function isClosed(status) {
    return status === STATUS_DONE || status === STATUS_CANCELED;
}

function escapeMarkdownText(text) {
    return String(text).replace(/([\\\[\]])/g, "\\$1");
}

// Block titles are Logseq-flavored Markdown, and may come from other people
// (shared graphs, pasted text). Before Qt renders them:
//   - raw HTML is escaped, so it can't hide where a link goes or load images;
//   - images become plain text, so displaying a note never fetches anything;
// then [[Page]] references become links the widget can follow.
function toMarkdown(title) {
    if (!title)
        return "";
    var s = String(title)
        .replace(/</g, "\\<")       // no raw HTML or autolinks
        .replace(/!\[/g, "\\![");  // ![alt](url) and ![alt][ref] stay text
    return s.replace(/\[\[([^\[\]\n]+)\]\]/g, function (match, name) {
        var target = encodeURIComponent(name).replace(/[()]/g, function (c) {
            return "%" + c.charCodeAt(0).toString(16).toUpperCase();
        });
        return "[" + escapeMarkdownText(name) + "](" + PAGE_LINK_SCHEME + target + ")";
    });
}

// Graph text shown in places that auto-detect rich text (combo boxes, menus,
// tooltips, placeholders). A zero-width space after "<" stops Qt from
// treating it as HTML, without changing how it looks.
function plain(text) {
    return String(text === undefined || text === null ? "" : text).replace(/</g, "<\u200b");
}

// Only web and mail links open from the widget; file:, custom app handlers
// and the like are refused.
function isSafeExternalLink(link) {
    return /^(https?:\/\/|mailto:)/i.test(String(link));
}

// What a hovered link will do, for its tooltip.
function describeLink(link) {
    var page = pageFromLink(link);
    if (page.length > 0)
        return "[[" + page + "]]";
    return String(link);
}

function pageFromLink(link) {
    if (link.indexOf(PAGE_LINK_SCHEME) !== 0)
        return "";
    return decodeURIComponent(link.substring(PAGE_LINK_SCHEME.length));
}

function priorityKey(ident) {
    if (!ident)
        return "";
    var i = ident.lastIndexOf(".");
    return i >= 0 ? ident.substring(i + 1) : ident;
}

function logseqUrl(graph, page) {
    if (!graph)
        return "";
    var url = "logseq://graph/" + encodeURIComponent(graph);
    if (page)
        url += "?page=" + encodeURIComponent(page);
    return url;
}
