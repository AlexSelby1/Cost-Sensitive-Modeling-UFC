import numpy as np
import pandas as pd
from tqdm import tqdm
from statistics import mean
import sys
import os
from pathlib import Path
from scipy.spatial import distance
from sklearn.linear_model import LinearRegression

from PreProcessing.Imputer import Imputer
from FeatureEngineering.ewma import EWMA
from FeatureEngineering.ufc_elo import calculate_elos, calculate_expected
from FeatureEngineering.odds_utils import convert_american_odds_to_perecentage
from FeatureEngineering.WhoWonAtGraplingStriking import wrestling, striking, ground_and_pound, JiuJitsu, grappling, log_striking, log_defense
from FeatureEngineering.ESPNfeatures import ESPN_features
from FeatureEngineering.skill import calculate_skill
from FeatureEngineering.Fighter_Level_features import feature_engineering_fighter_level_loop, check_if_each_row_is_either_red_or_blue
from FeatureEngineering.Shift_Features import Shift_all_features
from FeatureEngineering.comparing_previous_opponents import get_stats_of_fighters_who_they_have_beaten_or_lost_to, Normalize_Features


class Engineering:

    def __init__(self):

        self.BASE_PATH  = Path(os.getcwd())
        
        self.read_files()
        self.create_total_fight_time()
        self.merge_files()
        self.find_which_odds_relate_to_which_fighter()
        self.calaculate_stamina()
        self.create_espn_features()
        print('Creating Fighter Level Attributes')
        self.create_fighter_level_attributes()
        self.create_elo_ratings()
        self.create_skill_based_features()
        self.GetStatsOfFightersWhoTheyHaveBeatenOrLostTo()
        self.check_if_fighter_beat_anyone_who_opponent_has_lost_to()

        print('Shift All Features')
        self.shift_features()
        self.calculate_average_distance_of_opponent_to_previous_wins_loses()
        self.calculate_fight_weights()
        self.get_expected_probabilites_from_elos()
        self.subset_features()
        self.Normalize_different_wins()
        self.save_file(filename='data/engineered_features.csv')

    
    def read_files(self):

        print('Reading Files')

        try:
            self.fight = pd.read_csv(self.BASE_PATH/'data/data.csv', parse_dates=['date'])
        
        except:
            raise FileNotFoundError('Cannot find the data/data.csv')

        
        try:
            self.raw_fight = pd.read_csv(self.BASE_PATH/'data/total_fight_data.csv', sep=';', parse_dates=['date'])
        
        except:
            raise FileNotFoundError('Cannot find the data/total_fight_data.csv')


        try:
            self.odds = pd.read_csv(self.BASE_PATH/'data/raw_fighter_odds.csv', parse_dates=['Date'])[['Fighter_one','Fighter_two','Average_Odds_f1','Average_Odds_f2','Date']]
            self.odds.Average_Odds_f1 = pd.to_numeric(self.odds.Average_Odds_f1)
            self.odds.Average_Odds_f2 = pd.to_numeric(self.odds.Average_Odds_f2)
        except:
            raise FileNotFoundError('Cannot find the data/raw_fighter_odds.csv')


        try:
            self.best_fight_odds = pd.read_csv(self.BASE_PATH/'data/best_fight_odds.csv', parse_dates=['Date']) 

        except:
            raise FileNotFoundError('Cannot find the data/best_fight_odds.csv')



    @staticmethod
    def create_a_merge_column(df, fighter_one, fighter_two, date):

        df['merge'] = df[fighter_one] + df[fighter_two] 
        df['merge'] = df['merge'].apply(lambda x: x.replace(" ", "").replace(".",""))
        df['merge'] = df['merge'].apply(lambda x: ''.join(sorted(x)))
        df['merge'] = df['merge'] + df[date].astype(str)

        return(df)


    @staticmethod
    def calculate_time(last_round_time, last_round):
        
        if last_round_time >= 5:
            return(last_round*5)

        else:
            return((last_round*5)+last_round_time)

    
    def create_total_fight_time(self):
        self.raw_fight.last_round_time = self.raw_fight.last_round_time.apply(lambda x: float(x.replace(':','.')))
        self.raw_fight['total_fight_time'] = (np.where(self.raw_fight.last_round_time >= 5, 
                                                       self.raw_fight.last_round*5,
                                                       ((self.raw_fight.last_round-1)*5) + self.raw_fight.last_round_time))


    def create_merge_cols(self):

        self.odds = self.create_a_merge_column(self.odds, 'Fighter_one', 'Fighter_two', 'Date')
        self.fights = self.create_a_merge_column(self.fight, 'R_fighter', 'B_fighter', 'date')
        self.raw_fight = self.create_a_merge_column(self.raw_fight, 'R_fighter', 'B_fighter', 'date')
        self.best_fight_odds = self.create_a_merge_column(self.best_fight_odds, 'fighter1', 'fighter2', 'Date')


    def merge_files(self):

        self.create_merge_cols()
        self.fights_and_odds = self.fights.merge(self.odds,on='merge')

        # swap columns when needed
        self.fights_and_odds.Average_Odds_f1, self.fights_and_odds.Average_Odds_f2 = (np.where(self.fights_and_odds.R_fighter == self.fights_and_odds.Fighter_one, 
                                                                             [self.fights_and_odds.Average_Odds_f1, self.fights_and_odds.Average_Odds_f2], 
                                                                             [self.fights_and_odds.Average_Odds_f2, self.fights_and_odds.Average_Odds_f1]))


        self.fights_and_odds['red_Fighter_Odds']   = self.fights_and_odds.Average_Odds_f1.apply(lambda x: convert_american_odds_to_perecentage(x))
        self.fights_and_odds['blue_Fighter_Odds']  = self.fights_and_odds.Average_Odds_f2.apply(lambda x: convert_american_odds_to_perecentage(x))

        
        raw_fight_selected = self.raw_fight[['win_by','total_fight_time','B_GROUND','R_GROUND','B_CLINCH','R_CLINCH','B_DISTANCE',
                                            'R_DISTANCE','B_LEG','R_LEG','B_BODY','R_BODY','B_HEAD','R_HEAD','B_REV','R_REV',
                                            'B_PASS','R_PASS','B_SUB_ATT','R_SUB_ATT','B_TD_pct','R_TD_pct','B_TD','R_TD',
                                            'B_TOTAL_STR.','R_TOTAL_STR.','B_SIG_STR_pct','R_SIG_STR_pct','B_SIG_STR.','R_SIG_STR.',
                                            'B_KD','R_KD','merge']]


        self.fights_and_odds = self.fights_and_odds.merge(raw_fight_selected, on = 'merge')
        self.fights_and_odds = self.fights_and_odds.merge(self.best_fight_odds, on = 'merge',
                                                          how='left', suffixes=('', '_y'))

        self.fights_and_odds.drop(self.fights_and_odds.filter(regex='_y$').columns.tolist(),axis=1, inplace=True)


        # drop duplicates two odds for same fight
        self.fights_and_odds.drop_duplicates(subset=['merge'], keep='first',inplace=True)
        self.fights_and_odds.drop(['merge','Fighter_one','Fighter_two','Date',
                              'Referee','location'], inplace = True, axis = 1)

    
    @staticmethod
    def find_mismatch(row, fighter_one_cols, fighter_two_cols):

        if(row.R_fighter != row.fighter1) & (row.R_fighter == row.fighter2):
            
            for fighter_one, fighter_two in zip(fighter_one_cols, fighter_two_cols):
                row[fighter_one], row[fighter_two] = row[fighter_two], row[fighter_one]

        else:
            pass


        return row


    @staticmethod
    def find_fighter1_and_fighter2_cols(df):

        subset_cols_one = [col for col in df.columns.to_list() if 'red_fighter' in col]
        subset_cols_two = [col.replace('red_fighter', 'blue_fighter') for col in subset_cols_one]

        return subset_cols_one, subset_cols_two



    def find_which_odds_relate_to_which_fighter(self):

        fighter_one_cols, fighter_two_cols = self.find_fighter1_and_fighter2_cols(self.fights_and_odds)
        self.fights_and_odds = self.fights_and_odds.apply(lambda x: self.find_mismatch(x, fighter_one_cols, fighter_two_cols), axis=1)



    def create_espn_features(self):

        (self.fights_and_odds['red_strikes_per_minute'],
        self.fights_and_odds['blue_strikes_per_minute'],
        self.fights_and_odds['red_striking_accuracy'],
        self.fights_and_odds['blue_striking_accuracy'],
        self.fights_and_odds['red_avg_takedowns'],
        self.fights_and_odds['blue_avg_takedowns'],
        self.fights_and_odds['red_td_accuracy'],
        self.fights_and_odds['blue_td_accuracy'],
        self.fights_and_odds['red_td_defense'],
        self.fights_and_odds['blue_td_defense'],
        self.fights_and_odds['red_strikes_absorbed_per_minute'],
        self.fights_and_odds['blue_strikes_absorbed_per_minute'],
        self.fights_and_odds['red_striking_defense'],
        self.fights_and_odds['blue_striking_defense'],
        self.fights_and_odds['red_avg_submissions'],
        self.fights_and_odds['blue_avg_submissions'],
        self.fights_and_odds['red_knockdowns'],
        self.fights_and_odds['blue_knockdowns'],
        self.fights_and_odds['red_power'],
        self.fights_and_odds['blue_power'],
        self.fights_and_odds['red_total_striking_ratio'],
        self.fights_and_odds['blue_total_striking_ratio'],
        self.fights_and_odds['red_total_takedown_percentage'],
        self.fights_and_odds['blue_total_takedown_percentage'],
        self.fights_and_odds['red_strikes_or_grapple'],
        self.fights_and_odds['blue_strikes_or_grapple'],) = zip(*self.fights_and_odds.apply(lambda x: ESPN_features(x), axis=1))

    
    def create_elo_ratings(self):
        self.Elos_and_features = calculate_elos(self.Elos_and_features)


    def create_skill_based_features(self):

        self.Elos_and_features['Who_Won_at_Wrestling']    = self.Elos_and_features.apply(lambda x: wrestling(x), axis=1)
        self.Elos_and_features['Who_Won_at_Striking']     = self.Elos_and_features.apply(lambda x: striking(x), axis=1)
        self.Elos_and_features['Who_Won_at_Ground&Pound'] = self.Elos_and_features.apply(lambda x: ground_and_pound(x), axis=1)
        self.Elos_and_features['Who_Won_at_JiuJitsu']     = self.Elos_and_features.apply(lambda x: JiuJitsu(x), axis=1)
        self.Elos_and_features['Who_Won_at_Grappling']    = self.Elos_and_features.apply(lambda x: grappling(x), axis=1)

        self.Elos_and_features['who_won_log_striking']    = self.Elos_and_features.apply(lambda x: log_striking(x), axis=1)
        self.Elos_and_features['who_won_log_defense']    = self.Elos_and_features.apply(lambda x: log_defense(x), axis=1)


        self.Elos_and_features = calculate_skill(self.Elos_and_features, 'Winner',
                                            'red_skill','blue_skill')
        self.Elos_and_features = calculate_skill(self.Elos_and_features, 'Who_Won_at_Wrestling',
                                            'wrestling_red_skill','wrestling_blue_skill')
        self.Elos_and_features = calculate_skill(self.Elos_and_features, 'Who_Won_at_Striking',
                                            'striking_red_skill','striking_blue_skill')
        self.Elos_and_features = calculate_skill(self.Elos_and_features, 'Who_Won_at_Ground&Pound',
                                            'g_and_p_red_skill','g_and_p_blue_skill')
        self.Elos_and_features = calculate_skill(self.Elos_and_features, 'Who_Won_at_JiuJitsu',
                                            'jiujitsu_red_skill', 'jiujitsu_blue_skill')
        self.Elos_and_features = calculate_skill(self.Elos_and_features, 'Who_Won_at_Grappling',
                                            'grappling_red_skill','grappling_blue_skill')
        self.Elos_and_features = calculate_skill(self.Elos_and_features, 'who_won_log_striking',
                                            'log_striking_red_skill','log_striking_blue_skill')
        self.Elos_and_features = calculate_skill(self.Elos_and_features, 'who_won_log_defense',
                                            'log_defense_red_skill','log_defense_blue_skill')
        


    def create_fighter_level_attributes(self):
        
        new_features = feature_engineering_fighter_level_loop(self.fights_and_odds)
        add_variable_to_split = check_if_each_row_is_either_red_or_blue(new_features, self.fights_and_odds)

        red = add_variable_to_split[add_variable_to_split.Blue_or_Red == 'Red'].rename(columns = {'Fight_Number':'R_Fight_Number',
                                                         'WinLossRatio':'R_WinLossRatio','RingRust':'R_RingRust',
                                                         'AVG_fight_time':'R_AVG_fight_time','Winning_Streak':'R_Winning_Streak',
                                                          'Losing Streak':'R_Losing_Streak',
                                                          'Takedown_Defense':'R_Takedown_Defense',
                                                          'Takedown Accuracy':'R_Takedown Accuracy',
                                                          'Strikes_Per_Minute':'R_Strikes_Per_Minute',
                                                          'Striking Accuracy':'R_Striking Accuracy',
                                                          'Strikes_Absorbed_per_Minute':'R_Strikes_Absorbed_per_Minute',
                                                          'Striking Defense':'R_Striking Defense',
                                                          'Submission Attempts':'R_Submission Attempts',
                                                          'Average_Num_Takedowns':'R_Average_Num_Takedowns',
                                                          'knockdows_per_minute':'R_knockdows_per_minute',
                                                          'Power_Rating':'R_Power_Rating',
                                                          'Log_Striking_Ratio':'R_Log_Striking_Ratio',
                                                          'Beaten_Names':'R_Beaten_Names',
                                                          'Lost_to_names': 'R_Lost_to_names',
                                                          'Log_Striking_Defense':'R_Log_Striking_Defense',
                                                          'Total_Takedown_Percentage':'R_Total_Takedown_Percentage',
                                                          'average_strikes_or_grapple':'R_average_strikes_or_grapple',
                                                          'opponents_avg_strikes_or_grapple':'R_opponents_avg_strikes_or_grapple',
                                                          'opp_log_striking_ratio':'R_opp_log_striking_ratio',
                                                          'opp_log_of_striking_defense':'R_opp_log_of_striking_defense',
                                                          'odds_varience':'R_odds_varience',
                                                          'finish_ratio':'R_finish_ratio'}).set_index('Index')

        red.drop(['Blue_or_Red','Fighters'], inplace=True,axis=1)

        blue = add_variable_to_split[add_variable_to_split.Blue_or_Red == 'Blue'].rename(columns = {'Fight_Number':'B_Fight_Number',
                                                         'WinLossRatio':'B_WinLossRatio','RingRust':'B_RingRust',
                                                         'AVG_fight_time':'B_AVG_fight_time','Winning_Streak':'B_Winning_Streak',
                                                          'Losing Streak':'B_Losing_Streak',
                                                          'Takedown_Defense':'B_Takedown_Defense',
                                                          'Takedown Accuracy':'B_Takedown Accuracy',
                                                          'Strikes_Per_Minute':'B_Strikes_Per_Minute',
                                                          'Striking Accuracy':'B_Striking Accuracy',
                                                          'Strikes_Absorbed_per_Minute':'B_Strikes_Absorbed_per_Minute',
                                                          'Striking Defense':'B_Striking Defense',
                                                          'Submission Attempts':'B_Submission Attempts',
                                                          'Average_Num_Takedowns':'B_Average_Num_Takedowns',
                                                          'knockdows_per_minute':'B_knockdows_per_minute',
                                                          'Power_Rating':'B_Power_Rating',
                                                          'Log_Striking_Ratio':'B_Log_Striking_Ratio',
                                                          'Beaten_Names':'B_Beaten_Names',
                                                          'Lost_to_names': 'B_Lost_to_names',
                                                          'Log_Striking_Defense':'B_Log_Striking_Defense',
                                                          'Total_Takedown_Percentage':'B_Total_Takedown_Percentage',
                                                          'average_strikes_or_grapple':'B_average_strikes_or_grapple',
                                                          'opponents_avg_strikes_or_grapple':'B_opponents_avg_strikes_or_grapple',
                                                          'opp_log_striking_ratio':'B_opp_log_striking_ratio',
                                                          'opp_log_of_striking_defense':'B_opp_log_of_striking_defense',
                                                          'odds_varience':'B_odds_varience',
                                                          'finish_ratio':'B_finish_ratio'}).set_index('Index')


        blue.drop(['Blue_or_Red','Fighters'], inplace=True,axis=1)

        self.Elos_and_features = self.fights_and_odds.join(red)
        self.Elos_and_features = self.Elos_and_features.join(blue)



    def GetStatsOfFightersWhoTheyHaveBeatenOrLostTo(self):

        the_features = get_stats_of_fighters_who_they_have_beaten_or_lost_to(self.Elos_and_features)
        add_variable_to_split = check_if_each_row_is_either_red_or_blue(the_features, self.Elos_and_features)

        red_attributes = add_variable_to_split[add_variable_to_split.Blue_or_Red == 'Red'].rename(columns = {
            'Stats_of_Opponents_they_have_beaten' :'R_Stats_of_Opponents_they_have_beaten',
            'Stats_of_Opponents_they_have_lost_to':'R_Stats_of_Opponents_they_have_lost_to'}).set_index('Index')

        red_attributes.drop(['Blue_or_Red','Fighters'], inplace=True,axis=1)

        blue_attributes = add_variable_to_split[add_variable_to_split.Blue_or_Red == 'Blue'].rename(columns = {
            'Stats_of_Opponents_they_have_beaten' :'B_Stats_of_Opponents_they_have_beaten',
            'Stats_of_Opponents_they_have_lost_to':'B_Stats_of_Opponents_they_have_lost_to'}).set_index('Index')

        blue_attributes.drop(['Blue_or_Red','Fighters'], inplace=True,axis=1)

        self.Elos_and_features = self.Elos_and_features.join(red_attributes)
        self.Elos_and_features = self.Elos_and_features.join(blue_attributes)



    def shift_features(self):
        '''
        Shift features as they need to be an accumaltion of stats before fight
        '''
        self.shifted_elos_and_features = Shift_all_features(self.Elos_and_features)


    @staticmethod
    def check_if_fighter_has_beaten_opponent_and_who_beat_their_current_opponent(row):
        
        R_beaten = set(row['R_Beaten_Names'])
        R_lost   = set(row['R_Lost_to_names'])

        B_beaten = set(row['B_Beaten_Names'])
        B_lost   = set(row['B_Lost_to_names'])

        if (len(R_beaten) > 0) and (len(B_lost) > 0):
            Red_beat = len(list(R_beaten & B_lost))
        else:
            Red_beat = 0

        if (len(B_beaten) > 0) and (len(R_lost) > 0):
            Blue_beat = len(list(B_beaten & R_lost))
        else:
            Blue_beat = 0

        return Red_beat, Blue_beat
        

    @staticmethod
    def Average_distance_of_oppent_to_wins_and_loses(row):

        blue_fighter = [row['B_Log_Striking_Defense'], row['blue_fighter median'],
                row['B_Log_Striking_Defense'],  row['B_age'],
                row['B_avg_opp_CLINCH_landed'], row['B_avg_GROUND_landed']]

        red_fighter  = [row['R_Log_Striking_Defense'], row['red_fighter median'],
                row['R_Log_Striking_Defense'],  row['R_age'],
                row['R_avg_opp_CLINCH_landed'], row['R_avg_GROUND_landed']]


        if len(row['R_Stats_of_Opponents_they_have_beaten']) > 0:
            distances = []
            for fighter in row['R_Stats_of_Opponents_they_have_beaten']:
                distances.append(distance.euclidean(blue_fighter, fighter))
            
            distance_red_beaten = EWMA(distances, 2)
        else:
            distance_red_beaten = 9999


        if len(row['R_Stats_of_Opponents_they_have_lost_to']) > 0:
            distances = []
            for fighter in row['R_Stats_of_Opponents_they_have_lost_to']:
                distances.append(distance.euclidean(blue_fighter, fighter))
            
            distance_red_lost = mean(distances)
        else:
            distance_red_lost = 9999


        if len(row['B_Stats_of_Opponents_they_have_beaten']) > 0:
            distances = []
            for fighter in row['B_Stats_of_Opponents_they_have_beaten']:
                distances.append(distance.euclidean(red_fighter, fighter))
            
            distance_blue_beaten = EWMA(distances, 2)
        else:
            distance_blue_beaten = 9999

        if len(row['B_Stats_of_Opponents_they_have_lost_to']) > 0:
            distances = []
            for fighter in row['B_Stats_of_Opponents_they_have_lost_to']:
                distances.append(distance.euclidean(red_fighter, fighter))
            
            distance_blue_lost = mean(distances)
        else:
            distance_blue_lost = 9999

        return distance_red_beaten, distance_red_lost, distance_blue_beaten, distance_blue_lost



    def calculate_average_distance_of_opponent_to_previous_wins_loses(self):


        subset_cols = ['R_fighter','B_fighter','date','title_bout', 'win_by','weight_class', 'Average_Odds_f1', 'Average_Odds_f2',
                   'red_fighters_elo','blue_fighters_elo','red_Fighter_Odds','blue_Fighter_Odds','Winner',
                   'R_Fight_Number', 'R_Height_cms', 'R_Reach_cms', 'R_age', 'R_WinLossRatio', 
                   'R_RingRust','R_Winning_Streak','R_Losing_Streak','R_AVG_fight_time','R_total_title_bouts',
                   'R_Takedown_Defense', 'R_Takedown Accuracy','R_Strikes_Per_Minute', 'R_Log_Striking_Ratio' , 'R_Striking Accuracy',
                   'R_Strikes_Absorbed_per_Minute','R_Striking Defense','R_knockdows_per_minute','R_Submission Attempts',
                   'R_Average_Num_Takedowns','R_win_by_Decision_Majority','R_win_by_Decision_Split','R_win_by_Decision_Unanimous',
                   'R_win_by_KO/TKO', 'R_win_by_Submission', 'R_win_by_TKO_Doctor_Stoppage','R_Power_Rating','red_skill',
                   'wrestling_red_skill','striking_red_skill','g_and_p_red_skill', 'jiujitsu_red_skill', 'grappling_red_skill',
                   'R_Log_Striking_Defense', 'red_fighter median', 'blue_fighter median', 'B_avg_opp_CLINCH_landed', 'R_avg_opp_CLINCH_landed',
                   'R_avg_GROUND_landed','B_avg_GROUND_landed',
                   'B_Fight_Number', 'R_Stats_of_Opponents_they_have_beaten', 'R_Stats_of_Opponents_they_have_lost_to',
                   'B_Stats_of_Opponents_they_have_beaten', 'B_Stats_of_Opponents_they_have_lost_to',
                   'B_Height_cms','B_Reach_cms', 'B_age','B_WinLossRatio','B_RingRust','B_Winning_Streak', 
                   'B_Losing_Streak','B_AVG_fight_time', 'B_total_title_bouts','B_Takedown_Defense', 'B_Takedown Accuracy', 
                   'B_Strikes_Per_Minute','B_Striking Accuracy','B_Log_Striking_Ratio','B_Strikes_Absorbed_per_Minute','B_Striking Defense',
                   'B_knockdows_per_minute','B_Submission Attempts','B_Average_Num_Takedowns','B_win_by_Decision_Majority',
                   'B_win_by_Decision_Split','B_win_by_Decision_Unanimous','B_win_by_KO/TKO','B_win_by_Submission',
                   'B_win_by_TKO_Doctor_Stoppage','B_Power_Rating','blue_skill', 'wrestling_blue_skill', 'striking_blue_skill',
                   'g_and_p_blue_skill', 'jiujitsu_blue_skill', 'grappling_blue_skill',
                   'B_Log_Striking_Defense']


        cols_to_keep_whole = ['R_fighter','B_fighter','date', 'Average_Odds_f1', 'Average_Odds_f2',
                    'win_by','weight_class','Winner','R_win_by_Decision_Majority','R_win_by_Decision_Split', 'R_win_by_Decision_Unanimous',
                    'R_win_by_KO/TKO', 'R_win_by_Submission','R_win_by_TKO_Doctor_Stoppage','B_win_by_Decision_Majority',
                    'B_win_by_Decision_Split', 'B_win_by_Decision_Unanimous','B_win_by_KO/TKO', 'B_win_by_Submission',
                    'B_win_by_TKO_Doctor_Stoppage', 'R_Stats_of_Opponents_they_have_beaten', 'R_Stats_of_Opponents_they_have_lost_to',
                    'B_Stats_of_Opponents_they_have_beaten', 'B_Stats_of_Opponents_they_have_lost_to']


        temp  = Normalize_Features(self.shifted_elos_and_features, subset_cols, cols_to_keep_whole)
        
        (temp['R_distance_beaten'], 
         temp['R_distance_lost'], 
         temp['B_distance_beaten'],
         temp['B_distance_lost']) \
        =  zip(*temp.apply(lambda x: self.Average_distance_of_oppent_to_wins_and_loses(x), axis=1))
        
        temp = self.create_a_merge_column(temp, 'R_fighter', 'B_fighter', 'date')

        temp = temp[['R_distance_beaten','R_distance_lost','B_distance_beaten','B_distance_lost',
                    'merge']].copy()

        self.shifted_elos_and_features = self.create_a_merge_column(self.shifted_elos_and_features, 'R_fighter', 'B_fighter', 'date')
        self.shifted_elos_and_features = self.shifted_elos_and_features.merge(temp, on = 'merge')



    def check_if_fighter_beat_anyone_who_opponent_has_lost_to(self):

        (self.Elos_and_features['R_Beaten_Similar'], 
        self.Elos_and_features['B_Beaten_Similar']) \
        = zip(*self.Elos_and_features.apply(lambda x: self.check_if_fighter_has_beaten_opponent_and_who_beat_their_current_opponent(x), axis=1))


    def subset_features(self):
        
        self.subset = self.shifted_elos_and_features[['Average_Odds_f1', 'Average_Odds_f2','B_AVG_fight_time', 'B_Average_Num_Takedowns',
                                                    'B_Beaten_Names','B_Beaten_Similar','B_Fight_Number', 'B_Height_cms', 'B_Log_Striking_Defense',
                                                    'B_Log_Striking_Ratio','B_Losing_Streak','B_Lost_to_names','B_Power_Rating','B_Reach_cms',
                                                    'B_RingRust','B_Stance','B_Stats_of_Opponents_they_have_beaten','B_Stats_of_Opponents_they_have_lost_to',
                                                    'B_Strikes_Absorbed_per_Minute','B_Strikes_Per_Minute', 'B_Striking Accuracy','B_Striking Defense',
                                                    'B_Submission Attempts','B_Takedown Accuracy','B_Takedown_Defense','B_Total_Takedown_Percentage','B_Weight_lbs',
                                                    'B_WinLossRatio','B_Winning_Streak','B_age','B_avg_BODY_att','B_avg_BODY_landed',
                                                    'B_avg_CLINCH_att','B_avg_CLINCH_landed','B_avg_DISTANCE_att','B_avg_DISTANCE_landed','B_avg_GROUND_att',
                                                    'B_avg_GROUND_landed','B_avg_HEAD_att','B_avg_HEAD_landed','B_avg_KD','B_avg_LEG_att',
                                                    'B_avg_LEG_landed','B_avg_PASS','B_avg_REV','B_avg_SIG_STR_att','B_avg_SIG_STR_landed',
                                                    'B_avg_SIG_STR_pct','B_avg_SUB_ATT','B_avg_TD_att','B_avg_TD_landed','B_avg_TD_pct','B_avg_TOTAL_STR_att',
                                                    'B_avg_TOTAL_STR_landed','B_avg_opp_BODY_att','B_avg_opp_BODY_landed','B_avg_opp_CLINCH_att','B_avg_opp_CLINCH_landed',
                                                    'B_avg_opp_DISTANCE_att','B_avg_opp_DISTANCE_landed','B_avg_opp_GROUND_att','B_avg_opp_GROUND_landed','B_avg_opp_HEAD_att',
                                                    'B_avg_opp_HEAD_landed','B_avg_opp_KD','B_avg_opp_LEG_att','B_avg_opp_LEG_landed','B_avg_opp_PASS',
                                                    'B_avg_opp_REV','B_avg_opp_SIG_STR_att','B_avg_opp_SIG_STR_landed','B_avg_opp_SIG_STR_pct','B_avg_opp_SUB_ATT',
                                                    'B_avg_opp_TD_att','B_avg_opp_TD_landed','B_avg_opp_TD_pct','B_avg_opp_TOTAL_STR_att','B_avg_opp_TOTAL_STR_landed',
                                                    'B_current_lose_streak','B_current_win_streak','B_distance_beaten','B_distance_lost','B_draw','B_elo_expected',
                                                    'B_fighter','B_knockdows_per_minute','B_longest_win_streak','B_losses','B_odds_varience',
                                                    'B_opp_log_of_striking_defense','B_opp_log_striking_ratio','B_opponents_avg_strikes_or_grapple','B_total_rounds_fought','B_total_time_fought(seconds)','B_total_title_bouts',
                                                    'B_win_by_Decision_Majority','B_win_by_Decision_Split','B_win_by_Decision_Unanimous','B_win_by_KO/TKO','B_win_by_Submission',
                                                    'B_win_by_TKO_Doctor_Stoppage','B_wins','B_finish_ratio',
                                                    'R_AVG_fight_time','R_Average_Num_Takedowns','R_Beaten_Names','R_Beaten_Similar','R_Fight_Number','R_Height_cms',
                                                    'R_Log_Striking_Defense','R_Log_Striking_Ratio','R_Losing_Streak','R_Lost_to_names','R_Power_Rating',
                                                    'R_Reach_cms','R_RingRust','R_Stance','R_Stats_of_Opponents_they_have_beaten','R_Stats_of_Opponents_they_have_lost_to',
                                                    'R_Strikes_Absorbed_per_Minute','R_Strikes_Per_Minute','R_Striking Accuracy','R_Striking Defense',
                                                    'R_Submission Attempts','R_Takedown Accuracy','R_Takedown_Defense','R_Total_Takedown_Percentage','R_Weight_lbs',
                                                    'R_WinLossRatio','R_Winning_Streak','R_age','R_avg_BODY_att','R_avg_BODY_landed',
                                                    'R_avg_CLINCH_att','R_avg_CLINCH_landed','R_avg_DISTANCE_att','R_avg_DISTANCE_landed','R_avg_GROUND_att',
                                                    'R_avg_GROUND_landed','R_avg_HEAD_att','R_avg_HEAD_landed','R_avg_KD','R_avg_LEG_att',
                                                    'R_avg_LEG_landed','R_avg_PASS','R_avg_REV','R_avg_SIG_STR_att','R_avg_SIG_STR_landed','R_avg_SIG_STR_pct',
                                                    'R_avg_SUB_ATT','R_avg_TD_att','R_avg_TD_landed','R_avg_TD_pct','R_avg_TOTAL_STR_att',
                                                    'R_avg_TOTAL_STR_landed','R_avg_opp_BODY_att','R_avg_opp_BODY_landed','R_avg_opp_CLINCH_att','R_avg_opp_CLINCH_landed',
                                                    'R_avg_opp_DISTANCE_att','R_avg_opp_DISTANCE_landed','R_avg_opp_GROUND_att','R_avg_opp_GROUND_landed',
                                                    'R_avg_opp_HEAD_att','R_avg_opp_HEAD_landed','R_avg_opp_KD','R_avg_opp_LEG_att','R_avg_opp_LEG_landed',
                                                    'R_avg_opp_PASS','R_avg_opp_REV','R_avg_opp_SIG_STR_att','R_avg_opp_SIG_STR_landed','R_avg_opp_SIG_STR_pct',
                                                    'R_avg_opp_SUB_ATT','R_avg_opp_TD_att','R_avg_opp_TD_landed','R_avg_opp_TD_pct','R_avg_opp_TOTAL_STR_att',
                                                    'R_avg_opp_TOTAL_STR_landed','R_current_lose_streak','R_current_win_streak','R_distance_beaten','R_distance_lost',
                                                    'R_draw','R_elo_expected','R_fighter','R_knockdows_per_minute','R_longest_win_streak','R_losses','R_odds_varience',
                                                    'R_opp_log_of_striking_defense','R_opp_log_striking_ratio','R_opponents_avg_strikes_or_grapple','R_total_rounds_fought',
                                                    'R_total_time_fought(seconds)','R_total_title_bouts','R_win_by_Decision_Majority','R_win_by_Decision_Split','R_win_by_Decision_Unanimous',
                                                    'R_win_by_KO/TKO','R_win_by_Submission','R_win_by_TKO_Doctor_Stoppage','R_wins','Winner','R_finish_ratio',
                                                    'blue_Fighter_Odds',
                                                    'blue_fighter mean','blue_fighter median','blue_fighter max','blue_fighter wins by decision mean','blue_fighter wins by decision median',
                                                    'blue_fighter wins by decision max','blue_fighter wins by submission mean','blue_fighter wins by submission median','blue_fighter wins by submission max',
                                                    'blue_fighter wins by tko/ko mean','blue_fighter wins by tko/ko median','blue_fighter wins by tko/ko max','blue_fighter wins in round 1 mean',
                                                    'blue_fighter wins in round 1 median','blue_fighter wins in round 1 max','blue_fighter wins in round 2 mean',
                                                    'blue_fighter wins in round 2 median','blue_fighter wins in round 2 max','blue_fighter wins in round 3 mean','blue_fighter wins in round 3 median','blue_fighter wins in round 3 max',
                                                    'blue_fighters_elo','blue_skill','blue_stamina','date','fight_weight','g_and_p_blue_skill','g_and_p_red_skill','grappling_blue_skill',
                                                    'grappling_red_skill','jiujitsu_blue_skill','jiujitsu_red_skill','log_defense_blue_skill','log_defense_red_skill',
                                                    'log_striking_blue_skill','log_striking_red_skill','over 2½ rounds mean','over 2½ rounds median',
                                                    'over 2½ rounds max','red_Fighter_Odds',
                                                    'red_fighter mean','red_fighter median','red_fighter max','red_fighter wins by decision mean','red_fighter wins by decision median',
                                                    'red_fighter wins by decision max','red_fighter wins by submission mean','red_fighter wins by submission median','red_fighter wins by submission max','red_fighter wins by tko/ko mean',
                                                    'red_fighter wins by tko/ko median','red_fighter wins by tko/ko max','red_fighter wins in round 1 mean','red_fighter wins in round 1 median','red_fighter wins in round 1 max',
                                                    'red_fighter wins in round 2 mean','red_fighter wins in round 2 median','red_fighter wins in round 2 max','red_fighter wins in round 3 mean',
                                                    'red_fighter wins in round 3 median','red_fighter wins in round 3 max','red_fighters_elo','red_skill','red_stamina',
                                                    'striking_blue_skill','striking_red_skill','title_bout','under 2½ rounds mean','under 2½ rounds median',
                                                    'under 2½ rounds max','weight_class','win_by','wrestling_blue_skill','wrestling_red_skill',
                                                    'blue_fighter mean momentum', 'blue_fighter median momentum','blue_fighter max momentum','red_fighter mean momentum',
                                                    'red_fighter median momentum','red_fighter max momentum','over 2½ rounds mean momentum','over 2½ rounds median momentum',
                                                    'over 2½ rounds max momentum','under 2½ rounds mean momentum','under 2½ rounds median momentum','under 2½ rounds max momentum',
                                                    'red_fighter wins by decision mean momentum','red_fighter wins by decision median momentum','red_fighter wins by decision max momentum',
                                                    'blue_fighter wins by decision mean momentum','blue_fighter wins by decision median momentum','blue_fighter wins by decision max momentum',
                                                    'red_fighter wins by submission mean momentum','red_fighter wins by submission median momentum','red_fighter wins by submission max momentum',
                                                    'blue_fighter wins by submission mean momentum','blue_fighter wins by submission median momentum','blue_fighter wins by submission max momentum',
                                                    'red_fighter wins by tko/ko mean momentum','red_fighter wins by tko/ko median momentum','red_fighter wins by tko/ko max momentum',
                                                    'blue_fighter wins by tko/ko mean momentum','blue_fighter wins by tko/ko median momentum','blue_fighter wins by tko/ko max momentum',
                                                    'red_fighter wins in round 1 mean momentum','red_fighter wins in round 1 median momentum','red_fighter wins in round 1 max momentum',
                                                    'red_fighter wins in round 3 mean momentum','red_fighter wins in round 3 median momentum','red_fighter wins in round 3 max momentum',
                                                    'red_fighter wins in round 2 mean momentum','red_fighter wins in round 2 median momentum','red_fighter wins in round 2 max momentum',
                                                    'blue_fighter wins in round 3 mean momentum','blue_fighter wins in round 3 median momentum','blue_fighter wins in round 3 max momentum',
                                                    'blue_fighter wins in round 2 mean momentum','blue_fighter wins in round 2 median momentum','blue_fighter wins in round 2 max momentum',
                                                    'blue_fighter wins in round 1 mean momentum','blue_fighter wins in round 1 median momentum','blue_fighter wins in round 1 max momentum']]
        


    def get_expected_probabilites_from_elos(self):
        (self.shifted_elos_and_features['R_elo_expected'],
        self.shifted_elos_and_features['B_elo_expected']) = zip(*self.shifted_elos_and_features.apply(lambda x: calculate_expected(x), axis=1))


    def Normalize_different_wins(self):
        
        self.final = self.subset.copy()
        red_columns = ['R_win_by_Decision_Majority','R_win_by_Decision_Split','R_win_by_Decision_Unanimous',
                       'R_win_by_KO/TKO', 'R_win_by_Submission', 'R_win_by_TKO_Doctor_Stoppage']
                       
        blue_columns = ['B_win_by_Decision_Majority','B_win_by_Decision_Split','B_win_by_Decision_Unanimous',
                        'B_win_by_KO/TKO', 'B_win_by_Submission', 'B_win_by_TKO_Doctor_Stoppage']

        for red, blue in zip(red_columns, blue_columns):
            
            self.final[red]  = self.final[red]/self.final['R_Fight_Number']
            self.final[blue] = self.final[blue]/self.final['B_Fight_Number']



    def save_file(self, filename):
        self.final.to_csv(self.BASE_PATH/filename, index=False)


    @staticmethod
    def weight_fight(row):

        fight_time_minutes = row['total_fight_time']
        method_of_victory  = row['win_by']

        if (method_of_victory == "KO/TKO") | (method_of_victory == "Submission") | (method_of_victory == "TKO - Doctor's Stoppage"):
            flag = True
        else:
            flag = False
        

        if flag & (fight_time_minutes > 10):
            return 0.8
        elif flag & (fight_time_minutes <= 10) & (fight_time_minutes > 5):
            return 0.9
        elif flag & (fight_time_minutes <= 5) & (fight_time_minutes > 2.5):
            return 0.975
        elif flag & (fight_time_minutes <= 2.5):
            return 1

        elif method_of_victory == 'Decision - Unanimous':
            return 0.875
        elif method_of_victory == 'Decision - Majority':
            return 0.75
        elif method_of_victory == 'Decision - Split':
            return 0.6
        else:
            return 0.5



    def calculate_fight_weights(self):

        self.shifted_elos_and_features['fight_weight'] = self.shifted_elos_and_features.apply(lambda x: self.weight_fight(x), axis=1)


    @staticmethod
    def get_wins_round_data(row, red_or_blue):

        if red_or_blue == 'red':
            return np.array([row['red_fighter wins in round 1 mean'], row['red_fighter wins in round 2 mean'],	row['red_fighter wins in round 3 mean']]).reshape(-1, 1)
        
        else:
            return np.array([row['blue_fighter wins in round 1 mean'], row['blue_fighter wins in round 2 mean'],	row['blue_fighter wins in round 3 mean']]).reshape(-1, 1)


    @staticmethod
    def get_coefiecents(X, y):
        
        try:
            model = LinearRegression().fit(X, y)
            return model.coef_[0][0]

        except:
            return 9999

    

    def calaculate_stamina(self):


        X = np.array([1,2,3]).reshape(-1, 1)
        red_stamina = []
        blue_stamina = []

        for index, row in self.fights_and_odds.iterrows():
            
            y_blue = self.get_wins_round_data(row, red_or_blue='blue')
            y_red = self.get_wins_round_data(row, red_or_blue='red')
            
            red_stamina.append(self.get_coefiecents(X, y_red))
            blue_stamina.append(self.get_coefiecents(X, y_blue))

        self.fights_and_odds['red_stamina']  = red_stamina
        self.fights_and_odds['blue_stamina'] = blue_stamina

        return self.fights_and_odds













