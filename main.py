import json
import os
import firebase_admin
import pandas as pd
import requests
from firebase_admin import credentials, firestore
from flask import (
    Flask,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
    jsonify,
)
from fuzzywuzzy import fuzz
from gemini_utils import analyze_video, init_gemini
import re

app = Flask(__name__)

firebase_creds = json.loads(os.environ['FIREBASE_CREDENTIALS'])
cred = credentials.Certificate(firebase_creds)
firebase_admin.initialize_app(cred)
db = firestore.client()

# Load multiple home run datasets
csv_urls = [
    "https://storage.googleapis.com/gcp-mlb-hackathon-2025/datasets/2016-mlb-homeruns.csv",
    "https://storage.googleapis.com/gcp-mlb-hackathon-2025/datasets/2017-mlb-homeruns.csv",
    "https://storage.googleapis.com/gcp-mlb-hackathon-2025/datasets/2024-mlb-homeruns.csv",
    "https://storage.googleapis.com/gcp-mlb-hackathon-2025/datasets/2024-postseason-mlb-homeruns.csv",
]

# Concatenate all datasets
home_runs_df = pd.concat([pd.read_csv(url) for url in csv_urls],
                         ignore_index=True)

# --- Optimization: Convert 'title' to string type once ---
home_runs_df["title"] = home_runs_df["title"].astype(str)
print(f"Loaded {len(home_runs_df)} total home runs")


@app.route("/video/<player_id>")
@app.route("/video/<player_id>/<int:video_index>")
def video(player_id, video_index=0):
    try:
        if not player_id:
            return render_template('index.html',
                                   error="Invalid player ID"), 404

        player_info = get_player_info(player_id)
        if not player_info or 'people' not in player_info:
            return render_template(
                'index.html',
                error=f"Player with ID {player_id} not found"), 404

        player = player_info['people'][0]
        player_name = player['fullName']
        player_id = player['id']

        # Get team and position information
        doc_ref = db.collection('favorite_players').document(str(player_id))
        player_doc = doc_ref.get()
        if player_doc.exists:
            player_data = player_doc.to_dict()
            player_info['people'][0]['team'] = player_data.get('team', 'N/A')
        else:
            player_team, team_id = get_team_from_roster(player_id)
            player_info['people'][0][
                'team'] = player_team if player_team != 'N/A' else player_info[
                    'people'][0].get('currentTeam', {}).get('name', 'N/A')
        player_info['people'][0]['position'] = player_info['people'][0].get(
            'primaryPosition', {}).get('name', 'N/A')

        # Import get_all_home_runs at the top level
        from gemini_utils import get_all_home_runs
        # First try getting cached home runs
        home_runs = get_all_home_runs(player_name)

        # If we've seen all videos, refresh data from CSVs
        if video_index >= len(home_runs):
            # Reload CSV data
            global home_runs_df
            home_runs_df = pd.concat([pd.read_csv(url) for url in csv_urls],
                                     ignore_index=True)
            home_runs_df["title"] = home_runs_df["title"].astype(str)

            # Try getting home runs again with fresh data
            home_runs = get_all_home_runs(player_name)
            video_index = 0  # Reset index for new videos

        if not home_runs:
            return "No home run videos found for this player", 404

        # Check video cache first
        video_cache_ref = db.collection('video_cache').document(
            f"{player_id}_{video_index}")
        cache_doc = video_cache_ref.get()

        print(f"Checking cache for player {player_id}, video {video_index}")

        if cache_doc and cache_doc.exists:
            print("Loading from cache...")
            current_homer = cache_doc.to_dict()
            # Ensure all required fields are present
            required_fields = [
                'video', 'title', 'ExitVelocity', 'HitDistance', 'LaunchAngle'
            ]
            if all(field in current_homer for field in required_fields):
                print("Successfully loaded from cache")
            else:
                print("Cache entry incomplete, falling back to source data")
                current_homer = home_runs[video_index]
        else:
            print("Cache miss, loading from source...")
            current_homer = home_runs[video_index]

            # Extract home run number from title using multiple patterns
            hr_match = None
            hr_patterns = [
                r'homers?\s*\((\d+)\)',
                r'\((\d+)\)\s*on a',
                r'home run (?:no\.|number|#)\s*(\d+)',
                r'(\d+)(?:th|st|nd|rd)\s+home run',
            ]

            print("\n==== DEBUG: HR NUMBER EXTRACTION ====")
            print(f"DEBUG: Processing title: '{current_homer['title']}'")
            print(f"DEBUG: Full homer data: {current_homer}")

            for pattern in hr_patterns:
                print(f"\nDEBUG: Trying pattern: '{pattern}'")
                hr_match = re.search(pattern, current_homer['title'].lower())
                if hr_match:
                    print(f"DEBUG: MATCH FOUND with pattern '{pattern}'")
                    print(f"DEBUG: Matched group: '{hr_match.group(1)}'")
                    break
                print(f"DEBUG: No match for pattern '{pattern}'")

            hr_number = hr_match.group(1) if hr_match else None
            print(f"DEBUG: Extracted HR number: {hr_number}")
            print(f"DEBUG: Raw homer data: {current_homer}")

            # Set the home run number and print for debugging
            current_homer['hr_number'] = str(hr_number) if hr_number else None
            print(
                f"Extracted HR number: {current_homer['hr_number']} from title: {current_homer['title']}"
            )

            season_year = '2024'  # Default value
            for url in csv_urls:
                current_df = pd.read_csv(url)
                if current_homer['title'] in current_df['title'].values:
                    season_year = url.split('/')[-1].split('-')[0]
                    break

            current_homer['season_year'] = season_year

            # Update the video cache in database with simplified data structure
            try:
                print("\n==== DEBUG: CACHE OPERATION ====")
                hr_number_to_cache = str(hr_number) if hr_number else None
                print(f"DEBUG: HR number being cached: '{hr_number_to_cache}'")

                cache_data = {
                    'video': current_homer['video'],
                    'title': current_homer['title'],
                    'ExitVelocity': current_homer['ExitVelocity'],
                    'HitDistance': current_homer['HitDistance'],
                    'LaunchAngle': current_homer['LaunchAngle'],
                    'season_year': season_year,
                    'hr_number': hr_number_to_cache,
                    'cached_at': firestore.SERVER_TIMESTAMP
                }

                print("DEBUG: Writing cache data:")
                print(f"DEBUG: {cache_data}")
                video_cache_ref.set(cache_data)
                print("\nDEBUG: Cache data being set:")
                print(
                    f"DEBUG: HR Number in cache: {cache_data.get('hr_number')}"
                )
                print(f"DEBUG: Full cache data: {cache_data}")
                print("Successfully cached video data")
            except Exception as e:
                print(f"Error updating video cache: {e}")

            # Find which CSV file contains this home run and extract season year
            season_year = '2024'  # Default value
            current_title = current_homer['title']
            for url in csv_urls:
                df = pd.read_csv(url)
                if current_title in df['title'].values:
                    season_year = url.split('/')[-1].split('-')[0]
                    current_homer['season_year'] = season_year
                    break

            if 'season_year' not in current_homer:
                current_homer['season_year'] = season_year

            # Use the hr_number that was already extracted and stored
            current_homer['hr_number'] = str(hr_number) if hr_number else 'N/A'

            # Check for inside-the-park home run
            current_homer[
                'is_inside_park'] = 'inside-the-park' in current_homer[
                    'title'].lower()

            try:
                from datetime import datetime
                video_cache_ref.set({
                    'video':
                    current_homer['video'],
                    'title':
                    current_homer['title'],
                    'ExitVelocity':
                    current_homer['ExitVelocity'],
                    'HitDistance':
                    current_homer['HitDistance'],
                    'LaunchAngle':
                    current_homer['LaunchAngle'],
                    'season_year':
                    season_year,
                    'hr_number':
                    hr_number,
                    'cached_at':
                    firestore.SERVER_TIMESTAMP
                })

                # Get existing cache and append new video if it doesn't exist
                existing_cache = video_cache_ref.get()
                if existing_cache.exists:
                    existing_data = existing_cache.to_dict()
                    existing_videos = existing_data.get('videos', [])

                    # Check if video already exists
                    video_exists = any(
                        v.get('video_url') == current_homer['video']
                        for v in existing_videos)
                    if not video_exists:
                        existing_videos.append(cache_data['videos'][0])
                        video_cache_ref.update({'videos': existing_videos})
                else:
                    video_cache_ref.set(cache_data)
            except Exception as e:
                print(f"Error updating video cache: {e}")

        return render_template('video.html',
                               player_name=player_name,
                               player_id=str(player_id),
                               player=player_info['people'][0],
                               home_runs=home_runs,
                               video_index=video_index)
    except Exception as e:
        print(f"Error in video route: {e}")
        import traceback
        traceback.print_exc()
        return "Error fetching video", 500


@app.route("/stats/<player_id>")
def stats(player_id):
    try:
        print(f"DEBUG: Attempting to lookup player with ID: {player_id}")
        # Get player info using direct API call
        player_info = get_player_info(player_id)
        print(f"DEBUG: Player lookup result: {player_info}")
        if not player_info or 'people' not in player_info:
            print(f"DEBUG: No player found for ID: {player_id}")
            return "Player not found", 404

        player = player_info['people'][0]
        stats_by_year = {}

        try:
            # Initialize stats structure
            stats_by_year = {
                'career': {
                    'hitting': {},
                    'pitching': {},
                    'fielding': {}
                },
                'vsplayer': {
                    'total': {},
                    'splits': []
                }
            }

            # Get career stats and season stats
            stats_url = f"https://statsapi.mlb.com/api/v1/people/{player['id']}?hydrate=stats(group=[hitting,pitching,fielding],type=[career,yearByYear])"
            response = requests.get(stats_url)
            response.raise_for_status()
            stats_data = response.json()

            if 'people' in stats_data and stats_data['people']:
                player_stats = stats_data['people'][0].get('stats', [])
                for stat_group in player_stats:
                    group = stat_group.get('group', {}).get('displayName',
                                                            '').lower()
                    type_name = stat_group.get('type',
                                               {}).get('displayName', '')

                    if group in ['hitting', 'pitching', 'fielding']:
                        if type_name == 'career':
                            stats_by_year['career'][group] = {
                                'stat':
                                stat_group.get('splits',
                                               [{}])[0].get('stat', {}),
                                'team':
                                stat_group.get('splits',
                                               [{}])[0].get('team', {}),
                                'league':
                                stat_group.get('splits',
                                               [{}])[0].get('league', {}),
                                'position':
                                stat_group.get('splits',
                                               [{}])[0].get('position', {})
                            }
                        elif type_name == 'yearByYear':
                            if 'seasons' not in stats_by_year['career'][group]:
                                stats_by_year['career'][group]['seasons'] = []
                            stats_by_year['career'][group]['seasons'].extend(
                                stat_group.get('splits', []))

            # Get current team from favorite_players collection
            doc_ref = db.collection('favorite_players').document(
                str(player['id']))
            player_doc = doc_ref.get()
            if player_doc.exists:
                player_data = player_doc.to_dict()
                player['team'] = player_data.get('team')
                player['position'] = player_data.get('position')

            # Save stats to Firestore
            try:
                stats_ref = db.collection('player_stats').document(
                    str(player['id']))
                stats_data = {
                    'player_id': str(player['id']),
                    'name': player['fullName'],
                    'stats': stats_by_year,
                    'last_updated': firestore.SERVER_TIMESTAMP
                }
                stats_ref.set(stats_data)
                print(f"Successfully cached stats for {player['fullName']}")
            except Exception as e:
                print(f"Error caching stats: {e}")

            return render_template('stats.html',
                                   player=player,
                                   stats_by_year=stats_by_year)
        except Exception as e:
            print(f"Error fetching stats: {e}")
            return render_template('stats.html',
                                   player=player,
                                   stats_by_year={})
    except Exception as e:
        print(f"Error fetching stats: {e}")
        return "Error fetching player stats", 500



def get_player_info(player_id, season=None):
    """
    Fetches information about an MLB player using MLB-StatsAPI with caching.
    """
    import statsapi

    if not player_id or str(player_id) == "1":  # Skip invalid IDs
        return None

    try:
        # Check cache first
        player_cache_ref = db.collection('player_cache').document(
            str(player_id))
        cache_doc = player_cache_ref.get()

        if cache_doc.exists:
            cached_data = cache_doc.to_dict()
            # Return cached data if it exists and is not too old (24 hours)
            cached_at = cached_data.get('cached_at')
            if cached_at:
                from datetime import datetime
                import pytz

                utc = pytz.UTC
                now = datetime.now(utc)
                cached_time = cached_at.todate() if hasattr(
                    cached_at, 'todate') else cached_at
                if not cached_time.tzinfo:
                    cached_time = utc.localize(cached_time)

                time_diff = (now - cached_time).total_seconds()
                if time_diff < 86400:
                    print(f"Loading player info from cache for ID {player_id}")
                    return cached_data.get('player_info')

        # If not in cache or expired, fetch from API
        player_info = statsapi.get('person', {'personId': player_id})
        if season:
            player_info['people'][0]['stats'] = statsapi.player_stat_data(
                player_id, season)

        # Cache the result
        player_cache_ref.set({
            'player_info': player_info,
            'cached_at': firestore.SERVER_TIMESTAMP
        })

        print(f"Player info received and cached for ID {player_id}")
        return player_info
    except Exception as e:
        print(f"Error fetching player information: {e}")
        return None


def search_players(player_name):
    """
    Searches for MLB players by name using the Stats API and fuzzy matching.
    Handles name suffixes like Jr.
    """
    try:
        url = "https://statsapi.mlb.com/api/v1/sports/1/players"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()

        # Clean up input name
        clean_name = player_name.lower().replace('.', '').strip()

        # Create list of names with and without suffixes for matching
        player_matches = []
        for person in data['people']:
            full_name = person['fullName'].lower().replace('.', '')
            name_parts = full_name.split()

            # Try matching with and without suffix
            base_name = ' '.join(
                name_parts[:-1]) if len(name_parts) > 2 and name_parts[-1] in [
                    'jr', 'sr', 'ii', 'iii'
                ] else full_name

            score1 = fuzz.ratio(clean_name, full_name)
            score2 = fuzz.ratio(clean_name, base_name)
            max_score = max(score1, score2)

            if max_score > 70:
                player_matches.append((person, max_score))

        if player_matches:
            # Return the highest scoring match
            best_match = max(player_matches, key=lambda x: x[1])[0]
            return {'people': [best_match]}

        else:
            print(f"No close match found for {player_name}")
            return None

    except requests.exceptions.RequestException as e:
        print(f"Error searching for players: {e}")
        return None


def get_team_from_roster(player_id, season=2025):
    """
    Fetches the team name and team ID for a given player ID by checking team rosters with caching.
    """
    try:
        # Check cache first
        roster_cache_ref = db.collection('roster_cache').document(
            f"{player_id}_{season}")
        cache_doc = roster_cache_ref.get()

        if cache_doc.exists:
            cached_data = cache_doc.to_dict()
            # Return cached data if it exists and is not too old (12 hours)
            if cached_data.get('cached_at') and (
                    firestore.SERVER_TIMESTAMP -
                    cached_data.get('cached_at')).total_seconds() < 43200:
                print(f"Loading roster info from cache for player {player_id}")
                return cached_data.get('team_name'), cached_data.get('team_id')

        # Expanded list of MLB team IDs
        team_ids = list(range(108, 122)) + list(range(
            133, 148))  # Include more team IDs

        # First try getting team directly from player endpoint
        player_url = f'https://statsapi.mlb.com/api/v1/people/{player_id}?season={season}'
        player_response = requests.get(player_url)
        if player_response.status_code == 200:
            player_data = player_response.json()
            if 'people' in player_data and player_data['people']:
                current_team = player_data['people'][0].get('currentTeam', {})
                if current_team:
                    return current_team.get('name'), current_team.get('id')

        # If that fails, check each team's roster
        for team_id in team_ids:
            try:
                roster_url = f'https://statsapi.mlb.com/api/v1/teams/{team_id}/roster?season={season}'
                response = requests.get(roster_url)
                if response.status_code == 200:
                    roster_data = response.json()
                    if 'roster' in roster_data:
                        for player in roster_data['roster']:
                            if str(player.get('person',
                                              {}).get('id')) == str(player_id):
                                team_response = requests.get(
                                    f'https://statsapi.mlb.com/api/v1/teams/{team_id}'
                                )
                                if team_response.status_code == 200:
                                    team_data = team_response.json()
                                    team_name = team_data['teams'][0]['name']
                                    # Cache the result
                                    roster_cache_ref.set({
                                        'team_name':
                                        team_name,
                                        'team_id':
                                        team_id,
                                        'cached_at':
                                        firestore.SERVER_TIMESTAMP
                                    })
                                    return team_name, team_id
            except Exception as e:
                print(f"Error checking team {team_id}: {e}")
                continue

        return "N/A", None
    except Exception as e:
        print(f"Error fetching team from roster: {e}")
        return "N/A", None


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        player_name = request.form.get("player_name")
        if not player_name:
            return "Player name is required", 400

        player_info = search_players(player_name)
        if player_info and 'people' in player_info:
            player = player_info['people'][0]
            player_id = str(player['id'])

            doc_ref = db.collection('favorite_players').document(player_id)
            if not doc_ref.get().exists:
                player_team, team_id = get_team_from_roster(player_id)
                doc_ref.set({
                    'id': player_id,
                    'name': player['fullName'],
                    'team': player_team,
                    'position': player['primaryPosition']['name'],
                    'primaryNumber': player.get('primaryNumber', 'N/A'),
                    'votes': 0
                })

        return redirect(url_for('index'))

    favorite_players_ref = db.collection('favorite_players').stream()
    favorite_players = []
    for doc in favorite_players_ref:
        player_data = doc.to_dict()
        if 'id' not in player_data:
            player_data['id'] = doc.id
        favorite_players.append(player_data)

    # Sort players by votes in descending order
    favorite_players.sort(key=lambda x: x.get('votes', 0), reverse=True)

    print("Loaded players:",
          [f"{p['name']} (ID: {p['id']})" for p in favorite_players])

    return render_template("index.html", favorite_players=favorite_players)


@app.route("/vote/<player_id>")
def vote(player_id):
    try:
        print(f"Received vote request for player ID: {player_id}")
        player_id = str(player_id).strip()
        print(f"Looking up document with ID: {player_id}")

        doc_ref = db.collection('favorite_players').document(player_id)
        player_doc = doc_ref.get()
        print(f"Document exists: {player_doc.exists}")

        if player_doc.exists:
            current_votes = player_doc.to_dict().get('votes', 0)
            try:
                doc_ref.update({'votes': current_votes + 1})
                print("Votes updated successfully")
            except Exception as e:
                print(f"Error updating votes: {e}")
            return redirect(url_for('index'))
        else:
            return "Player not found", 404

    except Exception as e:
        print(f"Error updating votes: {e}")
        return "Error updating votes", 500


def get_player_id(player_name):
    """
    Get player ID from the Stats API using player name
    """
    try:
        player_info = search_players(player_name)
        if player_info and 'people' in player_info:
            return player_info['people'][0]['id']
        return None
    except Exception as e:
        print(f"Error getting player ID: {e}")
        return None


def analyze_video(video_url, player_name, homer_data):
    try:
        model = init_gemini()

        # Extract game ID from video URL
        game_id = video_url.split('/')[-1].split('-')[0]

        # Initialize default values
        home_team = 'Home Team'
        away_team = 'Away Team'
        home_score = 'N/A'
        away_score = 'N/A'
        inning = 'N/A'
        inning_state = ''
        inning_half = 'N/A'
        outs = 'N/A'
        count = 'N/A'
        base_situation = 'unknown'

        # Get detailed game data from MLB Stats API
        game_data = {}
        try:
            # Get complete game data from boxscore endpoint
            boxscore_url = f"https://statsapi.mlb.com/api/v1/game/{game_id}/boxscore"
            boxscore_response = requests.get(boxscore_url)
            teams_data = boxscore_response.json(
            ) if boxscore_response.status_code == 200 else {}

            home_team_data = teams_data.get('teams', {}).get('home', {})
            away_team_data = teams_data.get('teams', {}).get('away', {})

            # Get team names and scores
            home_team = home_team_data.get('team', {}).get('name', 'Home Team')
            away_team = away_team_data.get('team', {}).get('name', 'Away Team')
            home_score = home_team_data.get('teamStats',
                                            {}).get('batting',
                                                    {}).get('runs', 'N/A')
            away_score = away_team_data.get('teamStats',
                                            {}).get('batting',
                                                    {}).get('runs', 'N/A')

            # Get detailed game state from linescore endpoint
            linescore_url = f"https://statsapi.mlb.com/api/v1/game/{game_id}/linescore"
            linescore_response = requests.get(linescore_url)
            if linescore_response.status_code == 200:
                game_data = linescore_response.json()

                # Get inning details
                inning = game_data.get('currentInning', 'N/A')
                inning_state = game_data.get('inningState', '').lower()
                inning_half = 'top' if inning_state == 'top' else 'bottom'
                outs = game_data.get('outs', 'N/A')

                # Get baserunner situation
                offense = game_data.get('offense', {})
                bases = []
                if offense.get('first'): bases.append('first')
                if offense.get('second'): bases.append('second')
                if offense.get('third'): bases.append('third')
                base_situation = ', '.join(bases) if bases else 'bases empty'

                # Get count if available
                balls = game_data.get('balls', 'N/A')
                strikes = game_data.get('strikes', 'N/A')
                count = f"{balls}-{strikes}" if balls != 'N/A' and strikes != 'N/A' else 'N/A'

            # Get baserunner situation
            bases_occupied = []
            if game_data.get('offense', {}).get('first'):
                bases_occupied.append('first')
            if game_data.get('offense', {}).get('second'):
                bases_occupied.append('second')
            if game_data.get('offense', {}).get('third'):
                bases_occupied.append('third')

            base_situation = ', '.join(
                bases_occupied) if bases_occupied else 'bases empty'

        except Exception as e:
            print(f"Error fetching game data: {e}")
            inning = home_score = away_score = outs = 'N/A'
            home_team = away_team = 'Unknown Team'
            base_situation = 'unknown'
            inning_state = ''

        prompt = f"""
        You are an expert baseball analysis, analyzing this home run.

        Home Run Details:
        Batter: {player_name}
        Exit Velocity: {homer_data.get('ExitVelocity', 'N/A')} mph
        Hit Distance: {homer_data.get('HitDistance', 'N/A')} feet
        Launch Angle: {homer_data.get('LaunchAngle', 'N/A')}°
        Description: {homer_data.get('title', 'N/A')}

        Please analyze:
        The technical aspects of the home run (exit velocity, launch angle, distance)
        How these metrics compare to MLB averages (typical HR: 95-105 mph exit velo, 25-35° launch angle)

        """

        response = model.generate_content(prompt)
        analysis_text = response.text

        # Extract metrics from the analysis
        metrics = {
            'exit_velocity': float(homer_data.get('ExitVelocity', 0)),
            'estimated_distance': float(homer_data.get('HitDistance', 0)),
            'launch_angle': float(homer_data.get('LaunchAngle', 0))
        }

        return {'text': analysis_text, 'metrics': metrics}
    except Exception as e:
        print(f"Error in analyze_video: {e}")
        return {
            'text': "Error analyzing video",
            'metrics': {
                'exit_velocity': 0,
                'estimated_distance': 0,
                'launch_angle': 0
            }
        }


@app.route('/styles.css')
def serve_css():
    return send_from_directory(app.static_folder, 'styles.css')


@app.route("/api/analysis/<player_id>/<int:video_index>")
def get_analysis(player_id, video_index):
    try:
        player_info = get_player_info(player_id)
        if not player_info or 'people' not in player_info:
            return jsonify({'error': 'Player not found'}), 404

        player = player_info['people'][0]
        player_name = player['fullName']

        from gemini_utils import get_all_home_runs
        home_runs = get_all_home_runs(player_name)

        if not home_runs or video_index >= len(home_runs):
            return jsonify({'error': 'Video not found'}), 404

        current_homer = home_runs[video_index]

        # Check cache first
        cache_ref = db.collection('analysis_cache').document(
            f"{player_id}_{video_index}")
        cache_doc = cache_ref.get()

        if cache_doc.exists:
            analysis_result = cache_doc.to_dict()
            print("Loading analysis from cache")
        else:
            # Generate new analysis
            analysis_result = analyze_video(current_homer['video'],
                                            player_name, current_homer)
            # Cache the result
            try:
                cache_ref.set({
                    'text': analysis_result['text'],
                    'metrics': analysis_result['metrics'],
                    'player_id': player_id,
                    'video_index': video_index,
                    'cached_at': firestore.SERVER_TIMESTAMP
                })
                print("Cached new analysis")
            except Exception as e:
                print(f"Error caching analysis: {e}")
                pass

        # Generate HTML for the analysis
        lines = [
            line.strip() for line in analysis_result['text'].split('\n')
            if line.strip()
        ]
        html = '<div class="analysis-section">'

        for line in lines:
            line = line.replace('*', '').replace('**', '')  # Remove asterisks
            if ':' in line:
                label, content = line.split(':', 1)
                html += f'<div class="analysis-point"><strong>{label.strip()}:</strong>{content.strip()}</div>'
            else:
                html += f'<div class="analysis-text">{line}</div>'

        html += '</div>'

        return jsonify({'html': html})
    except Exception as e:
        print(f"Error generating analysis: {e}")
        return jsonify({'error': 'Error generating analysis'}), 500


if __name__ == "__main__":
    app.run(debug=True)
