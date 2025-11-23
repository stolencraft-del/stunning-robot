# pw.py
import os
import math
import uuid
import requests
import json
from typing import Tuple, Optional, List
from pyrogram import Client
from pyrogram.types import Message

API_BASE_V1 = "https://api.penpencil.co/v1"
API_BASE_V3 = "https://api.penpencil.co/v3"

# Your external custom player API template
# Example:
# https://anonymouspwplayer-25261acd1521.herokuapp.com/pw?url={url}&token={pw_token}
PLAYER_API_TEMPLATE = "https://anonymouspwplayer-25261acd1521.herokuapp.com/pw?url={url}&token={token}"


# -------------------------
# Helper: safe GET/POST
# -------------------------
def safe_get(url: str, params: dict = None, headers: dict = None, timeout: int = 20) -> Tuple[Optional[dict], Optional[str]]:
    try:
        r = requests.get(url, params=params, headers=headers, timeout=timeout)
        # Debug logging
        print(f"[PW] GET {r.url} -> {r.status_code}")
        try:
            data = r.json()
        except Exception as e:
            print(f"[PW] JSON decode error: {e} | text: {r.text[:400]}")
            return None, f"Invalid JSON response from server (status {r.status_code})."

        # Some responses use {"status": False, "message": "..."}
        if isinstance(data, dict):
            if data.get("status") is False:
                return None, data.get("message", "API returned status false")
            # Accept responses that put useful info under 'data' OR return list/dict directly
            return data, None
        else:
            # Not a dict (maybe list) - return raw data
            return data, None

    except requests.exceptions.RequestException as e:
        print(f"[PW] Request exception: {e}")
        return None, f"Request failed: {e}"


def safe_post(url: str, json_payload: dict = None, headers: dict = None, timeout: int = 20) -> Tuple[Optional[dict], Optional[str]]:
    try:
        r = requests.post(url, json=json_payload, headers=headers, timeout=timeout)
        print(f"[PW] POST {r.url} -> {r.status_code}")
        try:
            data = r.json()
        except Exception as e:
            print(f"[PW] JSON decode error (POST): {e} | text: {r.text[:400]}")
            return None, f"Invalid JSON response from server (status {r.status_code})."

        if isinstance(data, dict) and data.get("status") is False:
            return None, data.get("message", "API returned status false")

        return data, None
    except requests.exceptions.RequestException as e:
        print(f"[PW] Request exception (POST): {e}")
        return None, f"Request failed: {e}"


# -------------------------
# PW: get OTP (v1) - optional
# -------------------------
async def get_otp(client: Client, message: Message, phone_no: str) -> Tuple[bool, Optional[str]]:
    """
    Request OTP to phone_no. Returns (success, error_message)
    """
    url = f"{API_BASE_V1}/users/get-otp"
    query_params = {"smsType": "0"}
    headers = {
        "Content-Type": "application/json",
        "Client-Id": "5eb393ee95fab7468a79d189",
        "Client-Type": "WEB",
        "Client-Version": "2.6.12",
        "Integration-With": "Origin",
        "User-Agent": "Mozilla/5.0"
    }
    payload = {
        "username": phone_no,
        "countryCode": "+91",
        "organizationId": "5eb393ee95fab7468a79d189",
    }

    data, err = safe_post(url, json_payload=payload, headers=headers)
    if err:
        await message.reply_text(f"❌ Failed to generate OTP:\n{err}")
        return False, err

    # success check: many responses return {"status": True, "message": "xxx"}
    if isinstance(data, dict) and data.get("status") is False:
        return False, data.get("message", "Failed to generate OTP")

    return True, None


# -------------------------
# PW: get token (v3 oauth)
# -------------------------
async def get_token(client: Client, message: Message, phone_no: str, otp: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Exchanges OTP for a token. Returns (token, error).
    """
    url = f"{API_BASE_V3}/oauth/token"
    payload = {
        "username": phone_no,
        "otp": otp,
        "client_id": "system-admin",
        "client_secret": "KjPXuAVfC5xbmgreETNMaL7z",
        "grant_type": "password",
        "organizationId": "5eb393ee95fab7468a79d189",
        "latitude": 0,
        "longitude": 0
    }
    headers = {
        "Content-Type": "application/json",
        "Client-Id": "5eb393ee95fab7468a79d189",
        "Client-Type": "WEB",
        "Client-Version": "2.6.12",
        "User-Agent": "Mozilla/5.0"
    }

    data, err = safe_post(url, json_payload=payload, headers=headers)
    if err:
        await message.reply_text(f"❌ Token request failed:\n{err}")
        return None, err

    # expected: {"data": {"access_token": "..."}}
    if isinstance(data, dict) and "data" in data and isinstance(data["data"], dict):
        token = data["data"].get("access_token") or data["data"].get("accessToken") or data["data"].get("access_token")
        if token:
            return token, None

    # fallback: try to inspect common places
    if isinstance(data, dict) and data.get("access_token"):
        return data.get("access_token"), None

    await message.reply_text("❌ Could not extract token from response.")
    return None, "token_missing"


# -------------------------
# Core: login using token (safe)
# -------------------------
async def pw_login(client: Client, message: Message, token: str):
    """
    Main flow: uses token to fetch batches, list subjects, fetch topics and collect content URLs.
    Produces a per-user text file with lines in format:
      Topic Title : original_url | player_link
    """
    # prepare headers for v3
    headers = {
        "Host": "api.penpencil.co",
        "authorization": f"Bearer {token}",
        "client-id": "5eb393ee95fab7468a79d189",
        "client-version": "12.84",
        "user-agent": "Android",
        "randomid": str(uuid.uuid4())[:16],
        "client-type": "MOBILE",
        "content-type": "application/json; charset=UTF-8",
    }

    # Step 1: get batches (mode 1 or 2)
    params = {
        "mode": "1",
        "filter": "false",
        "exam": "",
        "amount": "",
        "organisationId": "5eb393ee95fab7468a79d189",
        "classes": "",
        "limit": "50",
        "page": "1",
        "programId": "",
    }

    data, err = safe_get(f"{API_BASE_V3}/batches/my-batches", params=params, headers=headers)
    if err:
        await message.reply_text(f"❌ Failed to fetch batches:\n{err}")
        return

    # Extract actual batches list from data depending on response structure
    batches = None
    if isinstance(data, dict) and "data" in data:
        # Some endpoints wrap payload into {"data": {...}}
        maybe = data["data"]
        if isinstance(maybe, list):
            batches = maybe
        elif isinstance(maybe, dict):
            batches = maybe.get("batches") or maybe.get("result") or maybe.get("payload") or []
    elif isinstance(data, list):
        batches = data

    if not batches:
        await message.reply_text("❌ No batches found in account.")
        return

    # Build list string
    text = "**You have these Batches :-**\n\n**Index** : **Batch Name**\n\n"
    for idx, b in enumerate(batches, start=1):
        # each b should contain '_id' and 'name' or 'batchId' etc.
        batch_id = b.get("_id") or b.get("batchId") or b.get("id")
        batch_name = b.get("name") or b.get("title") or "Unnamed Batch"
        text += f"{idx}. `{batch_id}` : **{batch_name}**\n"

    # Ask user to choose by index or send exact id
    reply = await client.ask(message.chat.id, text)
    reply_text = reply.text.strip()

    # allow user to send either numeric index or actual id
    selected_batch_id = None
    if reply_text.isdigit():
        idx = int(reply_text)
        if idx < 1 or idx > len(batches):
            return await reply.reply_text("❌ Invalid batch index.")
        selected_batch = batches[idx - 1]
        selected_batch_id = selected_batch.get("_id") or selected_batch.get("batchId") or selected_batch.get("id")
        selected_batch_name = selected_batch.get("name") or "Batch"
    else:
        # treat the text as ID
        selected_batch_id = reply_text
        # try to find name
        selected_batch_name = next((b.get("name") for b in batches if (b.get("_id") == selected_batch_id or b.get("batchId") == selected_batch_id or b.get("id") == selected_batch_id)), "Batch")

    await reply.reply_text(f"✔ Selected Batch: **{selected_batch_name}**")

    # Step 2: fetch batch details (subjects)
    details_data, err = safe_get(f"{API_BASE_V3}/batches/{selected_batch_id}/details", headers=headers, params=params)
    if err:
        await message.reply_text(f"❌ Failed to fetch batch details:\n{err}")
        return

    # Extract subjects list robustly
    subjects = []
    if isinstance(details_data, dict) and "data" in details_data:
        subjects = details_data["data"].get("subjects") or []
    elif isinstance(details_data, dict) and "subjects" in details_data:
        subjects = details_data.get("subjects") or []
    elif isinstance(details_data, list):
        subjects = details_data

    if not subjects:
        await message.reply_text("❌ No subjects found in the selected batch.")
        return

    # Build subject list and default subjectId string
    subj_text = "**Subject   :   SubjectId**\n\n"
    default_ids = []
    for s in subjects:
        subj = s.get("subject") or s.get("name") or "Unnamed"
        sid = s.get("subjectId") or s.get("_id") or s.get("id")
        tagcount = s.get("tagCount") or s.get("count") or 0
        subj_text += f"**{subj}**   :   `{sid}` (items: {tagcount})\n"
        if sid:
            default_ids.append(str(sid))
    await message.reply_text(subj_text)

    # Ask user to provide subject ids (1&2&3) or use default to download all
    default_entry = "&".join(default_ids)
    input4 = await client.ask(message.chat.id, text=(
        f"Now send the **Subject IDs** to Download\n\n"
        f"Send like this **1&2&3&4** or paste below ids to download full batch:\n\n`{default_entry}`"
    ))
    raw_text4 = input4.text.strip()
    if not raw_text4:
        return await input4.reply_text("❌ No subject IDs provided.")

    subject_ids = [s for s in raw_text4.split("&") if s]

    # Ask for resolution (if needed) - but for our purpose we'll just accept it but not enforce format
    input5 = await client.ask(message.chat.id, text="**Enter resolution (or type 'any')**")
    resolution = input5.text.strip() or "any"

    # Prepare temp filename per user
    tmp_filename = f"pw_{message.chat.id}_{uuid.uuid4().hex}.txt"
    try:
        # Open file and write headers
        with open(tmp_filename, "w", encoding="utf-8") as fp:
            fp.write(f"Batch: {selected_batch_name}\n\n")

        # For each subject id, fetch paginated topics/contents
        for subject_id in subject_ids:
            # Find tagCount for this subject if available so we know pages
            subj_obj = next((s for s in subjects if str(s.get("subjectId") or s.get("_id") or s.get("id")) == str(subject_id)), None)
            tagcount = 0
            if subj_obj:
                tagcount = int(subj_obj.get("tagCount") or subj_obj.get("count") or 0)

            # If tagcount unknown, we'll attempt pages until empty
            per_page = 20
            if tagcount > 0:
                total_pages = math.ceil(tagcount / per_page)
            else:
                total_pages = 10  # a safe upper bound, will break early if pages empty

            # Loop pages starting from 1..total_pages (inclusive)
            for page_num in range(1, total_pages + 1):
                params_page = {"page": str(page_num)}
                # Fetch topics for the subject (topics endpoint)
                topics_data, err = safe_get(f"{API_BASE_V3}/batches/{selected_batch_id}/subject/{subject_id}/topics", params=params_page, headers=headers)
                if err:
                    # Stop trying further pages for this subject on error
                    print(f"[PW] Error fetching topics page {page_num} subject {subject_id}: {err}")
                    break

                # Extract actual list of topic items
                topics_list = []
                if isinstance(topics_data, dict):
                    if "data" in topics_data and isinstance(topics_data["data"], list):
                        topics_list = topics_data["data"]
                    elif isinstance(topics_data.get("result"), list):
                        topics_list = topics_data.get("result")
                    else:
                        # Some variants return array directly as topics_data
                        possible = topics_data.get("topics") or topics_data.get("contents")
                        if isinstance(possible, list):
                            topics_list = possible
                elif isinstance(topics_data, list):
                    topics_list = topics_data

                # If no topics found on this page, break pagination loop for this subject
                if not topics_list:
                    print(f"[PW] No topics on page {page_num} for subject {subject_id}. Breaking.")
                    break

                # Process each topic item
                with open(tmp_filename, "a", encoding="utf-8") as fp:
                    for item in topics_list:
                        # Try to find title and url in common keys
                        title = item.get("topic") or item.get("title") or item.get("name") or "Untitled"
                        original_url = item.get("url") or item.get("resourceUrl") or item.get("attachmentUrl") or ""
                        # some items may contain nested attachment info
                        if not original_url:
                            # try to locate in nested fields
                            if isinstance(item.get("homeworkIds"), list) and item.get("homeworkIds"):
                                # ignore homework ids for now
                                original_url = ""
                        # Build player link using your external player (if original_url exists)
                        player_link = ""
                        if original_url:
                            # ensure url is urlencoded when substituting
                            from urllib.parse import quote_plus
                            player_link = PLAYER_API_TEMPLATE.format(url=quote_plus(original_url), token=token)

                        # Write both original and player link to file
                        line = f"{title} : {original_url} | {player_link}\n"
                        fp.write(line)

        # After collecting all, send the file
        await client.send_document(
            chat_id=message.chat.id,
            document=tmp_filename,
            caption=f"PW Extraction - Batch: {selected_batch_name}\nResolution requested: {resolution}"
        )
    except Exception as e:
        print(f"[PW] Exception: {e}")
        await message.reply_text(f"❌ Error while extracting: {e}")
    finally:
        # Clean up temp file
        try:
            if os.path.exists(tmp_filename):
                os.remove(tmp_filename)
        except Exception as e:
            print(f"[PW] Failed to remove tmp file: {e}")


# -------------------------
# Entry helpers to interact with users
# -------------------------
async def pw_mobile(client: Client, message: Message):
    """
    Ask the user for phone number, OTP flow, then call pw_login.
    """
    ask_phone = await client.ask(message.chat.id, text="**ENTER YOUR PW MOBILE NO. WITHOUT COUNTRY CODE.**")
    phone_no = ask_phone.text.strip()
    await ask_phone.delete()
    ok, err = await get_otp(client, message, phone_no)
    if not ok:
        return
    ask_otp = await client.ask(message.chat.id, text="**ENTER YOUR OTP SENT ON YOUR MOBILE NO.**")
    otp = ask_otp.text.strip()
    await ask_otp.delete()
    token, terr = await get_token(client, message, phone_no, otp)
    if not token:
        return
    await message.reply_text(f"**YOUR TOKEN** => `{token}`")
    await pw_login(client, message, token)


async def pw_token(client: Client, message: Message):
    """
    Ask the user directly for a token and call pw_login.
    """
    ask = await client.ask(message.chat.id, text="**ENTER YOUR PW ACCESS TOKEN**")
    token = ask.text.strip()
    await ask.delete()
    await pw_login(client, message, token)            'client-id': '5eb393ee95fab7468a79d189',

            'client-version': '12.84',

            'user-agent': 'Android',

            'randomid': 'e4307177362e86f1',

            'client-type': 'MOBILE',

            'device-meta': '{APP_VERSION:12.84,DEVICE_MAKE:Asus,DEVICE_MODEL:ASUS_X00TD,OS_VERSION:6,PACKAGE_NAME:xyz.penpencil.physicswalb}',

            'content-type': 'application/json; charset=UTF-8',

    }

    params = {
       'mode': '1',
       'filter': 'false',
       'exam': '',
       'amount': '',
       'organisationId': '5eb393ee95fab7468a79d189',
       'classes': '',
       'limit': '20',
       'page': '1',
       'programId': '',
       'ut': '1652675230446', 
    }
    response = requests.get('https://api.penpencil.co/v3/batches/my-batches', params=params, headers=headers).json()["data"]
    aa = "**You have these Batches :-\n\nBatch ID   :   Batch Name**\n\n"
    for data in response:
        batch = data["name"]
        aa += f"**{batch}**   :   `{data['_id']}`\n"
    await message.reply_text(aa)
    input3 = await app.ask(message.chat.id, text="**Now send the Batch ID to Download**")
    raw_text3 = input3.text
    response2 = requests.get(f'https://api.penpencil.co/v3/batches/{raw_text3}/details', headers=headers, params=params).json()
    subjects = response2.get('data', {}).get('subjects', [])
    bb = "**Subject   :   SubjectId**\n\n"
    vj = ""
    for subject in subjects:
        bb += f"**{subject.get('subject')}**   :   `{subject.get('subjectId')}`\n"
        vj += f"{subject.get('subjectId')}&"
    await message.reply_text(bb)
    input4 = await app.ask(message.chat.id, text=f"Now send the **Subject IDs** to Download\n\nSend like this **1&2&3&4** so on\nor copy paste or edit **below ids** according to you :\n\n**Enter this to download full batch :-**\n`{vj}`")
    raw_text4 = input4.text
    xu = raw_text4.split('&')
    hh = ""
    for x in range(0,len(xu)):
        s =xu[x]
        for subject in subjects:
            if subject.get('subjectId') == s:
                hh += f"{subject.get('subjectId')}:{subject.get('tagCount')}&"

    input5 = await app.ask(message.chat.id, text="**Enter resolution**")
    raw_text5 = input5.text
    
    try:
        xv = hh.split('&')
        cc = ""
        cv = ""
        for y in range(0,len(xv)):
            t =xv[y]
            id, tagcount = t.split(':')
            r = int(tagcount) / 20
            rr = math.ceil(r)

            for i in range(1,rr):
                params = {'page': str(i)}
                response3 = requests.get(f"https://api.penpencil.co/v3/batches/{raw_text3}/subject/{id}/topics", params=params, headers=headers).json()["data"]
#                for data in response3:
                with open(f"mm.txt", 'a') as f:
                    f.write(f"{response3}")   
            

            await app.send_document(message.chat.id, document=f"mm.txt")
    except Exception as e:
        await message.reply_text(str(e))





"""
params1 = {'page': '1','tag': '','contentType': 'videos'}
            response3 = requests.get(f'https://api.penpencil.co/v3/batches/{raw_text3}/subject/{t}/contents', params=params1, headers=headers).json()["data"]
            
            params2 = {'page': '1','tag': '','contentType': 'notes'}
            response4 = requests.get(f'https://api.penpencil.co/v3/batches/{raw_text3}/subject/{t}/contents', params=params2, headers=headers).json()["data"]

            try:
                for data in response3:
                    class_title = (data["topic"])
                    class_url = data["url"].replace("d1d34p8vz63oiq", "d26g5bnklkwsh4").replace("mpd", "m3u8").strip()
                    cc += f"{data['topic']}:{data['url']}\n"
                    with open(f"{batch}.txt", 'a') as f:
                        f.write(f"{cc}")

                for data in response4:
                    class_title = (lol["topic"])
                    for lol in data["homeworkIds"]:
                        concatenated_url = homework["attachmentIds"]["baseUrl"] + homework["attachmentIds"]["key"]
                    cv += f"{data['topic']}:{data['url']}\n"
                    with open(f"{batch}.txt", 'a') as f:
                        f.write(f"{cv}")
            except Exception as e:
               await message.reply_text(str(e))
"""
