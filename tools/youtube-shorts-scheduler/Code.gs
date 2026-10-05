/**
 * YouTube ショート 予約投稿ツール（Google Apps Script）
 *
 * Google スプレッドシートに「タイトル・説明・公開日」を書いておくと、
 * Google ドライブの動画を YouTube にアップロードし、指定日時に公開されるよう予約します。
 * 使い方は README.md を参照してください。
 */

const SHEET_POSTS = '投稿予定';
const SHEET_SETTINGS = '設定';

const HEADERS = ['投稿する', 'ファイル名', 'ファイルID', 'タイトル', '説明', 'タグ（カンマ区切り）', '公開日', '公開時刻', 'ステータス', '動画URL'];
const COL = { CHECK: 1, NAME: 2, FILE_ID: 3, TITLE: 4, DESC: 5, TAGS: 6, DATE: 7, TIME: 8, STATUS: 9, URL: 10 };

const SETTINGS_DEFAULTS = [
  ['動画フォルダ', '', 'アップロードする動画を置く Google ドライブのフォルダURL（またはID）'],
  ['投稿済みフォルダ', '', '（任意）予約が終わった動画を移動するフォルダURL。空欄なら移動しない'],
  ['割り振り開始日', '', '（任意）公開日を自動で割り振るときの開始日。空欄なら明日から'],
  ['投稿しない曜日', '土', '公開日を割り振るときに飛ばす曜日（例: 土 / 土日）'],
  ['公開時刻', '18:00', '公開時刻の初期値（24時間表記）'],
  ['カテゴリID', '22', '22 = ブログ（People & Blogs）'],
  ['子ども向け', 'いいえ', '「はい」にすると子ども向けコンテンツとして登録'],
  ['説明の末尾に付ける文', '', '（任意）全動画の説明欄の最後に付け足す文（ハッシュタグ・URLなど）'],
  ['タグの初期値', '', '（任意）ファイル取り込み時にタグ欄へ入れる値'],
];

const TZ = 'Asia/Tokyo';
const CHUNK_SIZE = 8 * 1024 * 1024; // 256KB の倍数にすること
const TIME_LIMIT_MS = 4.5 * 60 * 1000; // Apps Script の実行上限（6分）より手前で止める
const MIN_LEAD_MS = 15 * 60 * 1000; // 公開日時は少なくとも15分先
const WEEKDAYS = '日月火水木金土';

// ───────────────────────── メニュー ─────────────────────────

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('YouTube予約投稿')
    .addItem('① 初期設定（シート作成）', 'setupSheets')
    .addSeparator()
    .addItem('② ドライブから動画を取り込む', 'importFiles')
    .addItem('③ 公開日を自動で割り振る', 'assignDates')
    .addItem('④ 予約アップロードを実行', 'uploadScheduled')
    .addToUi();
}

// ───────────────────────── ① 初期設定 ─────────────────────────

function setupSheets() {
  const ss = SpreadsheetApp.getActive();

  let settings = ss.getSheetByName(SHEET_SETTINGS);
  if (!settings) {
    settings = ss.insertSheet(SHEET_SETTINGS);
    settings.getRange(1, 1, 1, 3).setValues([['項目', '値', '説明']]).setFontWeight('bold');
    settings.getRange('B:B').setNumberFormat('@'); // 「18:00」などを文字のまま保つ（値を入れる前に設定）
    settings.getRange(2, 1, SETTINGS_DEFAULTS.length, 3).setValues(SETTINGS_DEFAULTS);
    settings.getRange('B4').setNumberFormat('yyyy/mm/dd');
    settings.setColumnWidth(1, 160).setColumnWidth(2, 360).setColumnWidth(3, 480);
    settings.setFrozenRows(1);
  }

  let posts = ss.getSheetByName(SHEET_POSTS);
  if (!posts) {
    posts = ss.insertSheet(SHEET_POSTS, 0);
    posts.getRange(1, 1, 1, HEADERS.length).setValues([HEADERS]).setFontWeight('bold');
    posts.setFrozenRows(1);
    const rows = posts.getMaxRows() - 1;
    posts.getRange(2, COL.CHECK, rows, 1).insertCheckboxes();
    posts.getRange(2, COL.DATE, rows, 1).setNumberFormat('yyyy/mm/dd(ddd)');
    posts.getRange(2, COL.TIME, rows, 1).setNumberFormat('@');
    posts.getRange(2, COL.DESC, rows, 1).setWrap(true);
    posts.setColumnWidth(COL.CHECK, 70).setColumnWidth(COL.NAME, 200).setColumnWidth(COL.FILE_ID, 120)
      .setColumnWidth(COL.TITLE, 280).setColumnWidth(COL.DESC, 320).setColumnWidth(COL.TAGS, 180)
      .setColumnWidth(COL.DATE, 120).setColumnWidth(COL.TIME, 80).setColumnWidth(COL.STATUS, 220)
      .setColumnWidth(COL.URL, 260);
    posts.hideColumns(COL.FILE_ID);
  }

  notify_('シートを用意しました。「設定」シートに動画フォルダのURLを入れてください。');
}

// ───────────────────────── ② 動画の取り込み ─────────────────────────

function importFiles() {
  const settings = getSettings_();
  const folderId = extractId_(settings['動画フォルダ']);
  if (!folderId) throw new Error('「設定」シートの「動画フォルダ」が空です。');

  const sheet = getPostsSheet_();
  const known = new Set(getRows_(sheet).map(r => r.fileId).filter(Boolean));

  const found = [];
  const it = DriveApp.getFolderById(folderId).getFiles();
  while (it.hasNext()) {
    const f = it.next();
    if (!f.getMimeType().startsWith('video/') || known.has(f.getId())) continue;
    found.push(f);
  }
  found.sort((a, b) => a.getName().localeCompare(b.getName(), 'ja'));

  if (found.length === 0) {
    notify_('新しい動画はありませんでした。');
    return;
  }

  const defaultTags = settings['タグの初期値'] || '';
  const values = found.map(f => [true, f.getName(), f.getId(), f.getName().replace(/\.[^.]+$/, ''), '', defaultTags, '', '', '', '']);
  const start = lastDataRow_(sheet) + 1;
  sheet.getRange(start, 1, values.length, HEADERS.length).setValues(values);
  sheet.getRange(start, COL.CHECK, values.length, 1).insertCheckboxes().check();

  notify_(`${values.length} 本の動画を取り込みました。タイトル・説明を確認し、YouTube に出さない動画はチェックを外してください。`);
}

// ───────────────────────── ③ 公開日の割り振り ─────────────────────────

function assignDates() {
  const settings = getSettings_();
  const sheet = getPostsSheet_();
  const rows = getRows_(sheet);

  const skipDays = new Set(String(settings['投稿しない曜日'] || '').split('').map(c => WEEKDAYS.indexOf(c)).filter(i => i >= 0));
  if (skipDays.size >= 7) throw new Error('「投稿しない曜日」がすべての曜日になっています。');
  const defaultTime = normalizeTime_(settings['公開時刻']) || '18:00';

  const used = new Set(rows.filter(r => r.date instanceof Date).map(r => dayKey_(r.date)));

  let cursor = settings['割り振り開始日'] ? toDate_(settings['割り振り開始日']) : null;
  const tomorrow = startOfDay_(new Date(Date.now() + 24 * 60 * 60 * 1000));
  if (!cursor || cursor < tomorrow) cursor = tomorrow;

  let count = 0;
  rows.forEach(r => {
    if (!r.check || isDone_(r.status) || r.date) return;
    while (skipDays.has(dayOfWeek_(cursor)) || used.has(dayKey_(cursor))) cursor = addDays_(cursor, 1);
    sheet.getRange(r.row, COL.DATE).setValue(cursor);
    if (!r.time) sheet.getRange(r.row, COL.TIME).setValue(defaultTime);
    used.add(dayKey_(cursor));
    cursor = addDays_(cursor, 1);
    count++;
  });

  notify_(count ? `${count} 本に公開日を割り振りました。` : '公開日が空欄の動画（チェックあり）はありませんでした。');
}

// ───────────────────────── ④ 予約アップロード ─────────────────────────

function uploadScheduled() {
  runUploads_(false);
}

/** 時間切れで中断したときに、時間主導トリガーから自動で呼ばれる */
function continueUploads() {
  runUploads_(true);
}

/** @param {boolean} isContinuation 自動再開時は、今回すでに失敗した行を再試行しない */
function runUploads_(isContinuation) {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) {
    notify_('別のアップロードが実行中です。終わるまでお待ちください。');
    return;
  }
  try {
    deleteContinueTriggers_();
    const startedAt = Date.now();
    const settings = getSettings_();
    const sheet = getPostsSheet_();
    const doneFolderId = extractId_(settings['投稿済みフォルダ']);
    const targets = getRows_(sheet).filter(r => r.check && r.fileId && !isDone_(r.status)
      && !(isContinuation && r.status.startsWith('エラー')));

    let ok = 0, ng = 0;
    for (let i = 0; i < targets.length; i++) {
      if (Date.now() - startedAt > TIME_LIMIT_MS) {
        ScriptApp.newTrigger('continueUploads').timeBased().after(60 * 1000).create();
        notify_(`時間制限のため一旦止めました（成功 ${ok} / 失敗 ${ng}）。残り ${targets.length - i} 本は1分後に自動で再開します。`);
        return;
      }
      const r = targets[i];
      const statusCell = sheet.getRange(r.row, COL.STATUS);
      try {
        const publishAt = buildPublishAt_(r, settings);
        const metadata = buildMetadata_(r, settings, publishAt);
        statusCell.setValue('アップロード中…');
        SpreadsheetApp.flush();

        const video = uploadVideo_(r.fileId, metadata);
        statusCell.setValue(`予約済み（${Utilities.formatDate(publishAt, TZ, 'M/d HH:mm')} 公開）`);
        sheet.getRange(r.row, COL.URL).setValue(`https://youtube.com/shorts/${video.id}`);
        if (doneFolderId) DriveApp.getFileById(r.fileId).moveTo(DriveApp.getFolderById(doneFolderId));
        ok++;
      } catch (e) {
        statusCell.setValue('エラー: ' + e.message);
        ng++;
      }
      SpreadsheetApp.flush();
    }
    notify_(targets.length ? `完了しました（成功 ${ok} / 失敗 ${ng}）。` : '予約対象の動画はありませんでした。');
  } finally {
    lock.releaseLock();
  }
}

function buildPublishAt_(r, settings) {
  if (!(r.date instanceof Date)) throw new Error('公開日が入っていません');
  const time = normalizeTime_(r.time) || normalizeTime_(settings['公開時刻']) || '18:00';
  const [h, m] = time.split(':').map(Number);
  const d = r.date;
  // スクリプトのタイムゾーン（Asia/Tokyo）基準で日時を組み立てる
  const publishAt = new Date(d.getFullYear(), d.getMonth(), d.getDate(), h, m, 0);
  if (publishAt.getTime() - Date.now() < MIN_LEAD_MS) throw new Error('公開日時が過去、または15分以内です');
  return publishAt;
}

function buildMetadata_(r, settings, publishAt) {
  const title = String(r.title || '').trim();
  if (!title) throw new Error('タイトルが空です');
  if (title.length > 100) throw new Error(`タイトルが100文字を超えています（${title.length}文字）`);

  const footer = String(settings['説明の末尾に付ける文'] || '').trim();
  const description = [String(r.desc || '').trim(), footer].filter(Boolean).join('\n\n');
  if (description.length > 5000) throw new Error('説明が5000文字を超えています');
  if (/[<>]/.test(title + description)) throw new Error('タイトル・説明に「<」「>」は使えません');

  const tags = String(r.tags || '').split(/[,、，]/).map(t => t.trim()).filter(Boolean);

  return {
    snippet: {
      title: title,
      description: description,
      tags: tags,
      categoryId: String(settings['カテゴリID'] || '22'),
    },
    status: {
      privacyStatus: 'private', // publishAt を使うときは private 必須（指定日時に自動で公開される）
      publishAt: Utilities.formatDate(publishAt, TZ, "yyyy-MM-dd'T'HH:mm:ssXXX"),
      selfDeclaredMadeForKids: String(settings['子ども向け']).trim() === 'はい',
    },
  };
}

/**
 * ドライブの動画を YouTube へ分割（レジューマブル）アップロードする。
 * 1回の通信は 50MB までという Apps Script の制限を避けるため、8MB ずつ送る。
 */
function uploadVideo_(fileId, metadata) {
  const token = ScriptApp.getOAuthToken();
  const file = DriveApp.getFileById(fileId);
  const size = file.getSize();
  const mime = file.getMimeType();

  const init = UrlFetchApp.fetch(
    'https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status', {
      method: 'post',
      contentType: 'application/json; charset=UTF-8',
      payload: JSON.stringify(metadata),
      headers: {
        Authorization: 'Bearer ' + token,
        'X-Upload-Content-Length': String(size),
        'X-Upload-Content-Type': mime,
      },
      muteHttpExceptions: true,
    });
  if (init.getResponseCode() !== 200) throw new Error(apiError_('YouTube', init));
  const initHeaders = init.getHeaders();
  const sessionUrl = initHeaders['Location'] || initHeaders['location'];
  if (!sessionUrl) throw new Error('アップロード先URLを取得できませんでした');

  let start = 0;
  while (start < size) {
    const end = Math.min(start + CHUNK_SIZE, size) - 1;

    const chunk = UrlFetchApp.fetch(
      `https://www.googleapis.com/drive/v3/files/${fileId}?alt=media&supportsAllDrives=true`, {
        headers: { Authorization: 'Bearer ' + token, Range: `bytes=${start}-${end}` },
        muteHttpExceptions: true,
      });
    if (chunk.getResponseCode() !== 206 && chunk.getResponseCode() !== 200) throw new Error(apiError_('Drive', chunk));

    const res = UrlFetchApp.fetch(sessionUrl, {
      method: 'put',
      contentType: mime,
      payload: chunk.getContent(),
      headers: { Authorization: 'Bearer ' + token, 'Content-Range': `bytes ${start}-${end}/${size}` },
      muteHttpExceptions: true,
    });
    const code = res.getResponseCode();
    if (code === 200 || code === 201) return JSON.parse(res.getContentText());
    if (code !== 308) throw new Error(apiError_('YouTube', res));

    const resHeaders = res.getHeaders();
    const range = resHeaders['Range'] || resHeaders['range']; // 例: "bytes=0-8388607"
    start = range ? Number(range.split('-')[1]) + 1 : end + 1;
  }
  throw new Error('アップロードが完了しませんでした');
}

// ───────────────────────── 補助関数 ─────────────────────────

function getSettings_() {
  const sheet = SpreadsheetApp.getActive().getSheetByName(SHEET_SETTINGS);
  if (!sheet) throw new Error('「設定」シートがありません。メニューの「① 初期設定」を実行してください。');
  const map = {};
  sheet.getRange(2, 1, Math.max(sheet.getLastRow() - 1, 1), 2).getValues()
    .forEach(([k, v]) => { if (k) map[String(k).trim()] = v; });
  return map;
}

function getPostsSheet_() {
  const sheet = SpreadsheetApp.getActive().getSheetByName(SHEET_POSTS);
  if (!sheet) throw new Error('「投稿予定」シートがありません。メニューの「① 初期設定」を実行してください。');
  return sheet;
}

function getRows_(sheet) {
  const last = lastDataRow_(sheet);
  if (last < 2) return [];
  return sheet.getRange(2, 1, last - 1, HEADERS.length).getValues().map((v, i) => ({
    row: i + 2,
    check: v[COL.CHECK - 1] === true,
    name: v[COL.NAME - 1],
    fileId: String(v[COL.FILE_ID - 1] || '').trim(),
    title: v[COL.TITLE - 1],
    desc: v[COL.DESC - 1],
    tags: v[COL.TAGS - 1],
    date: v[COL.DATE - 1] instanceof Date ? v[COL.DATE - 1] : (v[COL.DATE - 1] ? toDate_(v[COL.DATE - 1]) : ''),
    time: v[COL.TIME - 1],
    status: String(v[COL.STATUS - 1] || ''),
  })).filter(r => r.fileId || r.name);
}

/** チェックボックスだけの行を除いた、データの入っている最終行 */
function lastDataRow_(sheet) {
  const n = sheet.getLastRow();
  if (n < 2) return 1;
  const ids = sheet.getRange(2, COL.NAME, n - 1, 2).getValues();
  for (let i = ids.length - 1; i >= 0; i--) {
    if (ids[i][0] !== '' || ids[i][1] !== '') return i + 2;
  }
  return 1;
}

function isDone_(status) {
  return String(status).startsWith('予約済み');
}

function extractId_(value) {
  const s = String(value || '').trim();
  if (!s) return '';
  const m = s.match(/folders\/([\w-]+)/) || s.match(/[?&]id=([\w-]+)/);
  return m ? m[1] : s;
}

/** 「18:00」「18時」や時刻セルの値を「HH:mm」にそろえる */
function normalizeTime_(v) {
  if (v instanceof Date) return Utilities.formatDate(v, TZ, 'HH:mm');
  const m = String(v || '').trim().replace(/[０-９：]/g, c => String.fromCharCode(c.charCodeAt(0) - 0xFEE0))
    .match(/^(\d{1,2})(?:[:時](\d{1,2})?)?分?$/);
  if (!m) return '';
  const h = Number(m[1]), min = Number(m[2] || 0);
  if (h > 23 || min > 59) return '';
  return `${String(h).padStart(2, '0')}:${String(min).padStart(2, '0')}`;
}

function toDate_(v) {
  if (v instanceof Date) return startOfDay_(v);
  const m = String(v).trim().match(/^(\d{4})[\/\-.年](\d{1,2})[\/\-.月](\d{1,2})/);
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : null;
}

function startOfDay_(d) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

function addDays_(d, n) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
}

function dayOfWeek_(d) {
  return d.getDay();
}

function dayKey_(d) {
  return Utilities.formatDate(d, TZ, 'yyyy-MM-dd');
}

function apiError_(service, res) {
  let msg = res.getContentText();
  try {
    const body = JSON.parse(msg);
    msg = (body.error && (body.error.message || body.error.errors?.[0]?.reason)) || msg;
  } catch (e) { /* JSON でなければそのまま */ }
  return `${service} ${res.getResponseCode()}: ${String(msg).slice(0, 200)}`;
}

function deleteContinueTriggers_() {
  ScriptApp.getProjectTriggers()
    .filter(t => t.getHandlerFunction() === 'continueUploads')
    .forEach(t => ScriptApp.deleteTrigger(t));
}

function notify_(message) {
  try {
    SpreadsheetApp.getUi().alert(message);
  } catch (e) {
    // トリガー実行中は画面がないので、トーストとログに残す
    SpreadsheetApp.getActive().toast(message, 'YouTube予約投稿', 10);
    console.log(message);
  }
}
