# pw.py - Complete Fixed Version
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
PLAYER_API_TEMPLATE = "https://anonymouspwplayer-25261acd1521.herokuapp.com/pw?url={url}&token={token}"


# -------------------------
# Helper: safe GET/POST
# -------------------------
def safe_get(url: str, params: dict = None, headers: dict = None, timeout: int = 20) -> Tuple[Optional[dict], Optional[str]]:
    """
    Safely perform GET request and return (data, error)
    """
    try:
        r = requests.get(url, params=params, headers=headers, timeout=timeout)
        print(f"[PW] GET {r.url} -> {r.status_code}")
        
        try:
            data = r.json()
        except Exception as e:
            print(f"[PW] JSON decode error: {e} | text: {r.text[:400]}")
            return None, f"Invalid JSON response from server (status {r.status_code})."

        if isinstance(data, dict):
            if data.get("status") is False:
                return None, data.get("message", "API returned status false")
            return data, None
        else:
            return data, None

    except requests.exceptions.RequestException as e:
        print(f"[PW] Request exception: {e}")
        return None, f"Request failed: {e}"


def safe_post(url: str, json_payload: dict = None, headers: dict = None, timeout: int = 20) -> Tuple[Optional[dict], Optional[str]]:
    """
    Safely perform POST request and return (data, error)
    """
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
# PW: get OTP (v1)
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

    # Try to extract token from various possible locations
    if isinstance(data, dict) and "data" in data and isinstance(data["data"], dict):
        token = data["data"].get("access_token") or data["data"].get("accessToken")
        if token:
            return token, None

    if isinstance(data, dict) and data.get("access_token"):
        return data.get("access_token"), None

    await message.reply_text("❌ Could not extract token from response.")
    return None, "token_missing"


# -------------------------
# Core: login using token
# -------------------------
async def pw_login(client: Client, message: Message, token: str):
    """
    Main flow: uses token to fetch batches, list subjects, fetch topics and collect content URLs.
    Produces a per-user text file with lines in format:
      Topic Title : original_url | player_link
    """
    # Prepare headers for API v3
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

    # Step 1: Get batches
    data, err = safe_get(f"{API_BASE_V3}/batches/my-batches", params=params, headers=headers)
    if err:
        await message.reply_text(f"❌ Failed to fetch batches:\n{err}")
        return

    # Extract batches list from response
    batches = None
    if isinstance(data, dict) and "data" in data:
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

    # Build batch selection list
    text = "**You have these Batches :-**\n\n**Index** : **Batch Name**\n\n"
    for idx, b in enumerate(batches, start=1):
        batch_id = b.get("_id") or b.get("batchId") or b.get("id")
        batch_name = b.get("name") or b.get("title") or "Unnamed Batch"
        text += f"{idx}. `{batch_id}` : **{batch_name}**\n"

    # Ask user to choose batch
    reply = await client.ask(message.chat.id, text)
    reply_text = reply.text.strip()

    # Allow user to send either numeric index or actual batch ID
    selected_batch_id = None
    if reply_text.isdigit():
        idx = int(reply_text)
        if idx < 1 or idx > len(batches):
            return await reply.reply_text("❌ Invalid batch index.")
        selected_batch = batches[idx - 1]
        selected_batch_id = selected_batch.get("_id") or selected_batch.get("batchId") or selected_batch.get("id")
        selected_batch_name = selected_batch.get("name") or "Batch"
    else:
        # Treat the text as batch ID
        selected_batch_id = reply_text
        selected_batch_name = next(
            (b.get("name") for b in batches 
             if (b.get("_id") == selected_batch_id or 
                 b.get("batchId") == selected_batch_id or 
                 b.get("id") == selected_batch_id)), 
            "Batch"
        )

    await reply.reply_text(f"✔ Selected Batch: **{selected_batch_name}**")

    # Step 2: Fetch batch details (subjects)
    details_data, err = safe_get(
        f"{API_BASE_V3}/batches/{selected_batch_id}/details", 
        headers=headers, 
        params=params
    )
    if err:
        await message.reply_text(f"❌ Failed to fetch batch details:\n{err}")
        return

    # Extract subjects list
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

    # Build subject list
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

    # Ask user for subject IDs
    default_entry = "&".join(default_ids)
    input4 = await client.ask(
        message.chat.id, 
        text=(
            f"Now send the **Subject IDs** to Download\n\n"
            f"Send like this **1&2&3&4** or paste below ids to download full batch:\n\n`{default_entry}`"
        )
    )
    raw_text4 = input4.text.strip()
    if not raw_text4:
        return await input4.reply_text("❌ No subject IDs provided.")

    subject_ids = [s.strip() for s in raw_text4.split("&") if s.strip()]

    # Ask for resolution preference
    input5 = await client.ask(message.chat.id, text="**Enter resolution (or type 'any')**")
    resolution = input5.text.strip() or "any"

    # Create temporary file for extraction
    tmp_filename = f"pw_{message.chat.id}_{uuid.uuid4().hex}.txt"
    
    try:
        # Write file header
        with open(tmp_filename, "w", encoding="utf-8") as fp:
            fp.write(f"Batch: {selected_batch_name}\n")
            fp.write(f"Resolution: {resolution}\n\n")

        # Process each subject
        for subject_id in subject_ids:
            # Find subject info to get tag count
            subj_obj = next(
                (s for s in subjects 
                 if str(s.get("subjectId") or s.get("_id") or s.get("id")) == str(subject_id)), 
                None
            )
            
            tagcount = 0
            if subj_obj:
                tagcount = int(subj_obj.get("tagCount") or subj_obj.get("count") or 0)
                subject_name = subj_obj.get("subject") or subj_obj.get("name") or "Unknown Subject"
            else:
                subject_name = f"Subject {subject_id}"

            # Calculate pagination
            per_page = 20
            if tagcount > 0:
                total_pages = math.ceil(tagcount / per_page)
            else:
                total_pages = 10  # Try up to 10 pages if count unknown

            print(f"[PW] Processing subject {subject_id} ({subject_name}), estimated pages: {total_pages}")

            # Write subject header
            with open(tmp_filename, "a", encoding="utf-8") as fp:
                fp.write(f"\n{'='*60}\n")
                fp.write(f"Subject: {subject_name}\n")
                fp.write(f"{'='*60}\n\n")

            # Fetch topics page by page
            for page_num in range(1, total_pages + 1):
                params_page = {"page": str(page_num)}
                
                topics_data, err = safe_get(
                    f"{API_BASE_V3}/batches/{selected_batch_id}/subject/{subject_id}/topics",
                    params=params_page,
                    headers=headers
                )
                
                if err:
                    print(f"[PW] Error fetching topics page {page_num} subject {subject_id}: {err}")
                    break

                # Extract topics list from response
                topics_list = []
                if isinstance(topics_data, dict):
                    if "data" in topics_data and isinstance(topics_data["data"], list):
                        topics_list = topics_data["data"]
                    elif isinstance(topics_data.get("result"), list):
                        topics_list = topics_data.get("result")
                    else:
                        possible = topics_data.get("topics") or topics_data.get("contents")
                        if isinstance(possible, list):
                            topics_list = possible
                elif isinstance(topics_data, list):
                    topics_list = topics_data

                # If no topics found, stop pagination for this subject
                if not topics_list:
                    print(f"[PW] No topics on page {page_num} for subject {subject_id}. Breaking.")
                    break

                print(f"[PW] Found {len(topics_list)} topics on page {page_num}")

                # Write topics to file
                with open(tmp_filename, "a", encoding="utf-8") as fp:
                    for item in topics_list:
                        # Extract topic details
                        title = item.get("topic") or item.get("title") or item.get("name") or "Untitled"
                        original_url = item.get("url") or item.get("resourceUrl") or item.get("attachmentUrl") or ""
                        
                        # Generate player link if URL exists
                        player_link = ""
                        if original_url:
                            from urllib.parse import quote_plus
                            player_link = PLAYER_API_TEMPLATE.format(
                                url=quote_plus(original_url), 
                                token=token
                            )

                        # Write to file
                        line = f"{title} : {original_url} | {player_link}\n"
                        fp.write(line)

        # Send the completed file
        await client.send_document(
            chat_id=message.chat.id,
            document=tmp_filename,
            caption=f"✅ PW Extraction Complete\n\n**Batch:** {selected_batch_name}\n**Resolution:** {resolution}"
        )
        
    except Exception as e:
        print(f"[PW] Exception during extraction: {e}")
        await message.reply_text(f"❌ Error while extracting: {e}")
        
    finally:
        # Clean up temporary file
        try:
            if os.path.exists(tmp_filename):
                os.remove(tmp_filename)
                print(f"[PW] Cleaned up temp file: {tmp_filename}")
        except Exception as e:
            print(f"[PW] Failed to remove tmp file: {e}")


# -------------------------
# Entry point: Mobile login flow
# -------------------------
async def pw_mobile(client: Client, message: Message):
    """
    Ask the user for phone number, request OTP, get token, then call pw_login.
    """
    ask_phone = await client.ask(
        message.chat.id, 
        text="**ENTER YOUR PW MOBILE NO. WITHOUT COUNTRY CODE.**"
    )
    phone_no = ask_phone.text.strip()
    await ask_phone.delete()
    
    # Request OTP
    ok, err = await get_otp(client, message, phone_no)
    if not ok:
        return
    
    # Ask for OTP
    ask_otp = await client.ask(
        message.chat.id, 
        text="**ENTER YOUR OTP SENT ON YOUR MOBILE NO.**"
    )
    otp = ask_otp.text.strip()
    await ask_otp.delete()
    
    # Exchange OTP for token
    token, terr = await get_token(client, message, phone_no, otp)
    if not token:
        return
    
    await message.reply_text(f"**YOUR TOKEN** => `{token}`")
    
    # Proceed with main login flow
    await pw_login(client, message, token)


# -------------------------
# Entry point: Token-based login
# -------------------------
async def pw_token(client: Client, message: Message):
    """
    Ask the user directly for a token and call pw_login.
    """
    ask = await client.ask(
        message.chat.id, 
        text="**ENTER YOUR PW ACCESS TOKEN**"
    )
    token = ask.text.strip()
    await ask.delete()
    
    # Proceed with main login flow
    await pw_login(client, message, token)
