import os
import requests


def init_gemini(multimodal=False):
    print("\n=== Initializing Gemini ===")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not found in environment variables")
        return None
    print("API key found")

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
    except ImportError as e:
        print(f"Error importing google.generativeai: {e}")
        return None

    if multimodal:
        generation_config = {
            "temperature": 1,
            "top_p": 0.95,
            "top_k": 40,
            "max_output_tokens": 8192,
            "response_mime_type": "text/plain",
        }
        model_name = "gemini-1.5-flash"
    else:
        generation_config = {
            "temperature": 0.7,
            "top_p": 0.8,
            "top_k": 40,
            "max_output_tokens": 2048,
        }
        model_name = "gemini-2.0-flash-exp"

    return genai.GenerativeModel(
        model_name=model_name,
        generation_config=generation_config,
    )


def upload_to_gemini(path, mime_type=None):
    """
    Uploads a file to Gemini for multimodal analysis
    """
    import google.generativeai as genai
    file = genai.upload_file(path, mime_type=mime_type)
    print(f"Uploaded file '{file.display_name}' as: {file.uri}")
    return file


def get_player_info(player_id, season=None):
    """
    Fetches detailed information about an MLB player from the Stats API.
    """
    if not player_id or str(player_id) == "1":  # Skip invalid IDs
        return None

    try:
        url = f"https://statsapi.mlb.com/api/v1/people/{player_id}"
        params = {}
        if season:
            params['season'] = season

        response = requests.get(url, params=params)
        if response.status_code == 404:
            print(f"Player ID {player_id} not found")
            return None
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching player information: {e}")
        return None


def analyze_video(player_name, homer_data):
    import logging
    import sys

    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('video_analysis.log')
        ]
    )

    try:
        logging.info("\n=== Starting Video Analysis ===")
        debug_print(f"Player Name: {player_name}")
        debug_print(f"Homer Data Type: {type(homer_data)}")
        debug_print(f"Homer Data Content: {homer_data}")

        # Initialize Gemini model
        print("\n=== Initializing Gemini Model ===")
        model = init_gemini()
        if not model:
            print("Error: Failed to initialize Gemini model")
            return {
                'text': "Error: Could not initialize Gemini model - check GEMINI_API_KEY",
                'metrics': {
                    'exit_velocity': 0,
                    'estimated_distance': 0,
                    'launch_angle': 0
                }
            }
        print("Gemini model initialized successfully")

        video_url = homer_data.get('video', '')
        game_id = video_url.split('/')[-1].split('-')[0] if video_url else ''

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
            response = requests.get(boxscore_url)
            response.raise_for_status()
            game_data = response.json()

            home_team = game_data.get('teams', {}).get('home', {}).get('team', {}).get('name', 'Home Team')
            away_team = game_data.get('teams', {}).get('away', {}).get('team', {}).get('name', 'Away Team')
            home_score = game_data.get('teams', {}).get('home', {}).get('score', 'N/A')
            away_score = game_data.get('teams', {}).get('away', {}).get('score', 'N/A')

            # Extract inning information (simplified example)
            linescore = game_data.get('linescore', {})
            inning = linescore.get('currentInning', 'N/A')
            inning_half = linescore.get('inningHalf', 'N/A')
            outs = linescore.get('outs', 'N/A')

            #Example of count data, needs adaptation based on actual data structure
            count = linescore.get('balls', 'N/A') + '-' + linescore.get('strikes','N/A')


        except requests.exceptions.RequestException as e:
            print(f"Error fetching game information: {e}")
        except Exception as e:
            print(f"Error processing game data: {e}")


        # Create analysis with metrics
        metrics = {
            'exit_velocity': float(homer_data.get('ExitVelocity', 0)),
            'estimated_distance': float(homer_data.get('HitDistance', 0)),
            'launch_angle': float(homer_data.get('LaunchAngle', 0))
        }

        prompt = f"""
        You are an expert baseball analysis, analyzing this home run.

        Home Run Details:
        Batter: {player_name}
        Exit Velocity: {homer_data.get('ExitVelocity', 'N/A')} mph
        Hit Distance: {homer_data.get('HitDistance', 'N/A')} feet
        Launch Angle: {homer_data.get('LaunchAngle', 'N/A')}°
        Description: {homer_data.get('title', 'N/A')}

        Game Context:
        Home Team: {home_team}
        Away Team: {away_team}
        Home Score: {home_score}
        Away Score: {away_score}
        Inning: {inning}
        Inning Half: {inning_half}
        Outs: {outs}
        Count: {count}

        Please analyze:
        The technical aspects of the home run (exit velocity, launch angle, distance)
        How these metrics compare to MLB averages (typical HR: 95-105 mph exit velo, 25-35° launch angle)
        The context of the home run within the game (score, inning, situation)
        """

        try:
            logging.info("\n=== Generating Analysis ===")
            logging.info("Sending prompt to Gemini...")
            logging.info("\n=== Sending Prompt to Gemini ===")
            logging.info(f"Prompt length: {len(prompt)}")
            logging.info("\n=== Sending Prompt ===")
            logging.info(f"Prompt:\n{prompt}")
            response = model.generate_content(prompt)
            logging.info("\n=== Response Received ===")
            logging.info(f"Raw Response: {response}")
            analysis_text = response.text
            debug_print(f"Analysis text length: {len(analysis_text)}")
            debug_print("Analysis content preview:", analysis_text[:200] + "...")
            debug_print("\n=== Analysis Complete ===")

            return {'text': analysis_text, 'metrics': metrics}
        except Exception as e:
            import traceback
            print("\n=== Analysis Error ===")
            print(f"Error Type: {type(e).__name__}")
            print(f"Error Message: {str(e)}")
            print("Traceback:")
            traceback.print_exc()
            return {
                'text': f"Error analyzing video: {str(e)}",
                'metrics': {
                    'exit_velocity': 0,
                    'estimated_distance': 0,
                    'launch_angle': 0
                }
            }
    except Exception as e:
        print(f"An unexpected error occurred in analyze_video: {e}")
        return {
                'text': f"An unexpected error occurred: {str(e)}",
                'metrics': {
                    'exit_velocity': 0,
                    'estimated_distance': 0,
                    'launch_angle': 0
                }
            }


def get_all_home_runs(player_name):
    """
    Get all home runs for a player.
    """
    try:
        from main import home_runs_df
        clean_player_name = player_name.lower().strip()
        names = clean_player_name.split()
        last_name = names[-1] if names else ""
        first_name = names[0] if names else ""

        # Convert title column to string type and handle NaN values
        home_runs_df['title'] = home_runs_df['title'].astype(str)

        # Look for titles that contain "homers" or "home run" after the player name
        homer_pattern = f"({clean_player_name.lower()}).*?(homers|home run)"
        player_home_runs = home_runs_df[
            home_runs_df['title'].str.lower().str.match(homer_pattern,
                                                        case=False)]

        # If no matches, try matching last name and first name separately
        if player_home_runs.empty and last_name and first_name:
            player_home_runs = home_runs_df[
                home_runs_df['title'].str.lower().str.contains(last_name,
                                                               case=False)
                & home_runs_df['title'].str.lower().str.contains(first_name,
                                                                 case=False)]

        if not player_home_runs.empty:
            return player_home_runs[[
                'title', 'video', 'ExitVelocity', 'HitDistance', 'LaunchAngle'
            ]].to_dict('records')
        return []
    except Exception as e:
        print(f"Error finding home runs: {e}")
        return []


if __name__ == "__main__":
    pass